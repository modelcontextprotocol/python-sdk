"""StreamableHTTP Session Manager for MCP servers."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import anyio
from anyio.abc import TaskStatus
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from mcp.server.streamable_http import (
    MCP_SESSION_ID_HEADER,
    EventStore,
    StreamableHTTPServerTransport,
)
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import INVALID_REQUEST, ErrorData, JSONRPCError

if TYPE_CHECKING:
    from mcp.server.lowlevel.server import Server

logger = logging.getLogger(__name__)


class StreamableHTTPSessionManager:
    """Manages StreamableHTTP sessions with optional resumability via event store.

    This class abstracts away the complexity of session management, event storage,
    and request handling for StreamableHTTP transports. It handles:

    1. Session tracking for clients
    2. Resumability via an optional event store
    3. Connection management and lifecycle
    4. Request handling and transport setup
    5. Idle session cleanup via optional timeout

    Important: Only one StreamableHTTPSessionManager instance should be created
    per application. The instance cannot be reused after its run() context has
    completed. If you need to restart the manager, create a new instance.

    Args:
        app: The MCP server instance
        event_store: Optional event store for resumability support. If provided, enables resumable connections
            where clients can reconnect and receive missed events. If None, sessions are still tracked but not
            resumable.
        json_response: Whether to use JSON responses instead of SSE streams
        stateless: If True, creates a completely fresh transport for each request with no session tracking or
            state persistence between requests.
        security_settings: Optional transport security settings.
        retry_interval: Retry interval in milliseconds to suggest to clients in SSE retry field. Used for SSE
            polling behavior.
        session_idle_timeout: Optional idle timeout in seconds for stateful sessions. If set, sessions that
            receive no HTTP requests for this duration will be automatically terminated and removed. When
            retry_interval is also configured, ensure the idle timeout comfortably exceeds the retry interval to
            avoid reaping sessions during normal SSE polling gaps. Default is None (no timeout). A value of 1800
            (30 minutes) is recommended for most deployments.
    """

    def __init__(
        self,
        app: Server[Any],
        event_store: EventStore | None = None,
        json_response: bool = False,
        stateless: bool = False,
        security_settings: TransportSecuritySettings | None = None,
        retry_interval: int | None = None,
        session_idle_timeout: float | None = None,
    ):
        if session_idle_timeout is not None and session_idle_timeout <= 0:
            raise ValueError("session_idle_timeout must be a positive number of seconds")
        if stateless and session_idle_timeout is not None:
            raise RuntimeError("session_idle_timeout is not supported in stateless mode")

        self.app = app
        self.event_store = event_store
        self.json_response = json_response
        self.stateless = stateless
        self.security_settings = security_settings
        self.retry_interval = retry_interval
        self.session_idle_timeout = session_idle_timeout

        # Session tracking (only used if not stateless)
        self._session_creation_lock = anyio.Lock()
        self._server_instances: dict[str, StreamableHTTPServerTransport] = {}

        # The task group will be set during lifespan
        self._task_group = None
        # Thread-safe tracking of run() calls
        self._run_lock = anyio.Lock()
        self._has_started = False

    @contextlib.asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        """Run the session manager with proper lifecycle management.

        This creates and manages the task group for all session operations.

        Important: This method can only be called once per instance. The same
        StreamableHTTPSessionManager instance cannot be reused after this
        context manager exits. Create a new instance if you need to restart.

        Use this in the lifespan context manager of your Starlette app:

        @contextlib.asynccontextmanager
        async def lifespan(app: Starlette) -> AsyncIterator[None]:
            async with session_manager.run():
                yield
        """
        # Thread-safe check to ensure run() is only called once
        async with self._run_lock:
            if self._has_started:
                raise RuntimeError(
                    "StreamableHTTPSessionManager .run() can only be called "
                    "once per instance. Create a new instance if you need to run again."
                )
            self._has_started = True

        async with anyio.create_task_group() as tg:
            # Store the task group for later use
            self._task_group = tg
            logger.info("StreamableHTTP session manager started")
            try:
                yield  # Let the application run
            finally:
                logger.info("StreamableHTTP session manager shutting down")
                # Cancel task group to stop all spawned tasks
                tg.cancel_scope.cancel()
                self._task_group = None
                # Clear any remaining server instances
                self._server_instances.clear()

    async def handle_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process ASGI request with proper session handling and transport setup.

        Dispatches to the appropriate handler based on stateless mode.
        """
        if self._task_group is None:
            raise RuntimeError("Task group is not initialized. Make sure to use run().")

        # Dispatch to the appropriate handler
        if self.stateless:
            await self._handle_stateless_request(scope, receive, send)
        else:
            await self._handle_stateful_request(scope, receive, send)

    async def _handle_stateless_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process request in stateless mode - creating a new transport for each request.

        Uses a request-scoped task group so the server task is automatically
        cancelled when the request completes, preventing task accumulation in
        the manager's global task group.
        """
        logger.debug("Stateless mode: Creating new transport for this request")
        # No session ID needed in stateless mode
        http_transport = StreamableHTTPServerTransport(
            mcp_session_id=None,  # No session tracking in stateless mode
            is_json_response_enabled=self.json_response,
            event_store=None,  # No event store in stateless mode
            security_settings=self.security_settings,
        )

        # Start server in a new task
        async def run_stateless_server(*, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED):
            async with http_transport.connect() as streams:
                read_stream, write_stream = streams
                task_status.started()
                try:
                    await self.app.run(
                        read_stream,
                        write_stream,
                        self.app.create_initialization_options(),
                        stateless=True,
                    )
                except Exception:  # pragma: lax no cover
                    logger.exception("Stateless session crashed")

        # Use a request-scoped task group instead of the global one.
        # This ensures the server task is cancelled when the request
        # finishes, preventing zombie tasks from accumulating.
        # See: https://github.com/modelcontextprotocol/python-sdk/issues/1764
        async with anyio.create_task_group() as request_tg:
            await request_tg.start(run_stateless_server)
            # Handle the HTTP request directly in the caller's context
            # (not as a child task) so execution flows back naturally.
            await http_transport.handle_request(scope, receive, send)
            # Cancel the request-scoped task group to stop the server task.
            request_tg.cancel_scope.cancel()

        # Terminate after the task group exits — the server task is already
        # cancelled at this point, so this is just cleanup (sets _terminated
        # flag and closes any remaining streams).
        await http_transport.terminate()

    async def _handle_stateful_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process request in stateful mode - maintaining session state between requests."""
        request = Request(scope, receive)
        request_mcp_session_id = request.headers.get(MCP_SESSION_ID_HEADER)

        # Existing session case
        if request_mcp_session_id is not None and request_mcp_session_id in self._server_instances:
            transport = self._server_instances[request_mcp_session_id]
            logger.debug("Session already exists, handling request directly")
            # Push back idle deadline on activity
            if transport.idle_scope is not None and self.session_idle_timeout is not None:
                transport.idle_scope.deadline = anyio.current_time() + self.session_idle_timeout  # pragma: no cover
            await transport.handle_request(scope, receive, send)
            return

        if request_mcp_session_id is None:
            # New session case
            logger.debug("Creating new transport")
            async with self._session_creation_lock:
                new_session_id = uuid4().hex
                http_transport = StreamableHTTPServerTransport(
                    mcp_session_id=new_session_id,
                    is_json_response_enabled=self.json_response,
                    event_store=self.event_store,  # May be None (no resumability)
                    security_settings=self.security_settings,
                    retry_interval=self.retry_interval,
                )

                assert http_transport.mcp_session_id is not None
                self._server_instances[http_transport.mcp_session_id] = http_transport
                logger.info(f"Created new transport with session ID: {new_session_id}")

                # Define the server runner
                async def run_server(*, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
                    async with http_transport.connect() as streams:
                        read_stream, write_stream = streams
                        task_status.started()
                        try:
                            # Use a cancel scope for idle timeout — when the
                            # deadline passes the scope cancels app.run() and
                            # execution continues after the ``with`` block.
                            # Incoming requests push the deadline forward.
                            idle_scope = anyio.CancelScope()
                            if self.session_idle_timeout is not None:
                                idle_scope.deadline = anyio.current_time() + self.session_idle_timeout
                                http_transport.idle_scope = idle_scope

                            with idle_scope:
                                await self.app.run(
                                    read_stream,
                                    write_stream,
                                    self.app.create_initialization_options(),
                                    stateless=False,
                                )

                            if idle_scope.cancelled_caught:
                                assert http_transport.mcp_session_id is not None
                                logger.info(f"Session {http_transport.mcp_session_id} idle timeout")
                                self._server_instances.pop(http_transport.mcp_session_id, None)
                                await http_transport.terminate()
                        except Exception:
                            logger.exception(f"Session {http_transport.mcp_session_id} crashed")
                        finally:
                            if (  # pragma: no branch
                                http_transport.mcp_session_id
                                and http_transport.mcp_session_id in self._server_instances
                                and not http_transport.is_terminated
                            ):
                                logger.info(
                                    "Cleaning up crashed session "
                                    f"{http_transport.mcp_session_id} from active instances."
                                )
                                del self._server_instances[http_transport.mcp_session_id]

                # Assert task group is not None for type checking
                assert self._task_group is not None
                # Start the server task
                await self._task_group.start(run_server)

                # Handle the HTTP request and return the response
                await http_transport.handle_request(scope, receive, send)
        else:
            # Unknown or expired session ID - return 404 per MCP spec
            # TODO: Align error code once spec clarifies
            # See: https://github.com/modelcontextprotocol/python-sdk/issues/1821
            error_response = JSONRPCError(
                jsonrpc="2.0",
                id=None,
                error=ErrorData(code=INVALID_REQUEST, message="Session not found"),
            )
            response = Response(
                content=error_response.model_dump_json(by_alias=True, exclude_unset=True),
                status_code=HTTPStatus.NOT_FOUND,
                media_type="application/json",
            )
            await response(scope, receive, send)


class StreamableHTTPASGIApp:
    """ASGI application for Streamable HTTP server transport."""

    def __init__(self, session_manager: StreamableHTTPSessionManager):
        self.session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.session_manager.handle_request(scope, receive, send)
