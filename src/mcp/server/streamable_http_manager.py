"""StreamableHTTP Session Manager for MCP servers."""

from __future__ import annotations

import contextlib
import logging
from collections import deque
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

import anyio
from anyio.abc import TaskStatus
from mcp_types import DEFAULT_NEGOTIATED_VERSION, INVALID_REQUEST, ErrorData, JSONRPCError
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from mcp.server._streamable_http_modern import handle_modern_request
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser, AuthorizationContext, authorization_context
from mcp.server.connection import Connection
from mcp.server.runner import serve_connection, serve_loop
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER, EventStore, StreamableHTTPServerTransport
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared._compat import resync_tracer
from mcp.shared.inbound import MCP_PROTOCOL_VERSION_HEADER
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.transport_context import TransportContext

if TYPE_CHECKING:
    from mcp.server.lowlevel.server import Server

logger = logging.getLogger(__name__)

DEFAULT_MAX_REQUEST_BODY_SIZE: Final = 4 * 1024 * 1024
"""Default maximum Streamable HTTP request body size in bytes (4 MiB)."""


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
        max_request_body_size: Maximum size in bytes for Streamable HTTP POST request bodies. Requests that
            exceed this limit receive a 413 response before parsing or session creation. Defaults to 4 MiB.
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
        max_request_body_size: int = DEFAULT_MAX_REQUEST_BODY_SIZE,
    ):
        if session_idle_timeout is not None and session_idle_timeout <= 0:
            raise ValueError("session_idle_timeout must be a positive number of seconds")
        if stateless and session_idle_timeout is not None:
            raise RuntimeError("session_idle_timeout is not supported in stateless mode")
        if max_request_body_size <= 0:
            raise ValueError("max_request_body_size must be a positive number of bytes")

        self.app = app
        self.event_store = event_store
        self.json_response = json_response
        self.stateless = stateless
        self.security_settings = security_settings
        self.retry_interval = retry_interval
        self.session_idle_timeout = session_idle_timeout
        self.max_request_body_size = max_request_body_size
        self.asgi_app = RequestBodyLimitMiddleware(self.handle_request, max_request_body_size)

        # Session tracking (only used if not stateless)
        self._session_creation_lock = anyio.Lock()
        self._server_instances: dict[str, StreamableHTTPServerTransport] = {}
        # Identity of the credential that created each session; requests for a
        # session must present the same credential.
        self._session_owners: dict[str, AuthorizationContext] = {}

        # The task group and lifespan state are set during run()
        self._task_group = None
        self._lifespan_state: Any = None
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

        async with self.app.lifespan(self.app) as lifespan_state, anyio.create_task_group() as tg:
            # Store for handle_request: lifespan is entered once for the
            # manager's lifetime, not per request (per-connection cleanup
            # belongs on `connection.exit_stack`).
            self._lifespan_state = lifespan_state
            self._task_group = tg
            logger.info("StreamableHTTP session manager started")
            try:
                yield  # Let the application run
            finally:
                logger.info("StreamableHTTP session manager shutting down")
                # Cancel task group to stop all spawned tasks
                tg.cancel_scope.cancel()
                self._task_group = None
                self._lifespan_state = None
                # Clear any remaining server instances
                self._server_instances.clear()
                self._session_owners.clear()
        await resync_tracer()

    async def handle_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process ASGI request with proper session handling and transport setup.

        Dispatches to the appropriate handler based on stateless mode.
        """
        if self._task_group is None:
            raise RuntimeError("Task group is not initialized. Make sure to use run().")

        # TODO(L49): header-only era-routing for now; body-primary classification
        # is a follow-up. The legacy paths below own only the known
        # initialize-handshake versions; anything else (including unknown
        # values) goes to the modern entry so the classifier can validate it
        # and return a structured rejection. 2025 paths below remain unchanged.
        header = MCP_PROTOCOL_VERSION_HEADER.encode("ascii")
        pv = next((v.decode("latin-1") for k, v in scope["headers"] if k == header), None)
        if pv is not None and pv not in HANDSHAKE_PROTOCOL_VERSIONS:
            await handle_modern_request(
                self.app, self.security_settings, self.json_response, self._lifespan_state, scope, receive, send
            )
            return

        # Dispatch to the appropriate handler
        if self.stateless:
            await self._handle_stateless_request(pv, scope, receive, send)
        else:
            await self._handle_stateful_request(scope, receive, send)

    async def _handle_stateless_request(
        self, protocol_version_hint: str | None, scope: Scope, receive: Receive, send: Send
    ) -> None:
        """Process request in stateless mode - creating a new transport for each request."""
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
                dispatcher: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(
                    read_stream,
                    write_stream,
                    inline_methods=frozenset({"initialize"}),
                    # No session ID means a server-to-client request can be
                    # written to this POST's response stream, but the client's
                    # reply has nowhere to land — `can_send_request=False`
                    # makes the per-request channel raise `NoBackChannelError`
                    # for requests while still allowing notifications.
                    transport_builder=lambda _md: TransportContext(kind="streamable-http", can_send_request=False),
                )
                # Born-ready, no standalone channel: the legacy stateless path
                # never opens a GET stream and need not see `initialize`. The
                # header (or the spec's default-absent value) seeds
                # `ctx.protocol_version`.
                connection = Connection.from_envelope(
                    protocol_version_hint if protocol_version_hint is not None else DEFAULT_NEGOTIATED_VERSION,
                    None,
                    None,
                )
                try:
                    await serve_connection(
                        self.app, dispatcher, connection=connection, lifespan_state=self._lifespan_state
                    )
                except Exception:  # pragma: lax no cover
                    logger.exception("Stateless session crashed")

        # Assert task group is not None for type checking
        assert self._task_group is not None
        # Start the server task
        await self._task_group.start(run_stateless_server)

        # Handle the HTTP request and return the response
        await http_transport.handle_request(scope, receive, send)

        # Terminate the transport after the request is handled
        await http_transport.terminate()

    async def _handle_stateful_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process request in stateful mode - maintaining session state between requests."""
        request = Request(scope, receive)
        request_mcp_session_id = request.headers.get(MCP_SESSION_ID_HEADER)

        user = scope.get("user")
        requestor = authorization_context(user) if isinstance(user, AuthenticatedUser) else None

        # Existing session case
        if request_mcp_session_id is not None and request_mcp_session_id in self._server_instances:
            transport = self._server_instances[request_mcp_session_id]
            if requestor != self._session_owners.get(request_mcp_session_id):
                # A session can only be used with the credential that created
                # it. Respond exactly as if the session did not exist.
                logger.warning(
                    "Rejecting request for session %s: credential does not match the one that created the session",
                    request_mcp_session_id[:64],
                )
                body = JSONRPCError(
                    jsonrpc="2.0", id=None, error=ErrorData(code=INVALID_REQUEST, message="Session not found")
                )
                response = Response(
                    body.model_dump_json(by_alias=True, exclude_unset=True),
                    status_code=404,
                    media_type="application/json",
                )
                await response(scope, receive, send)
                return
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
                if requestor is not None:
                    self._session_owners[http_transport.mcp_session_id] = requestor
                self._server_instances[http_transport.mcp_session_id] = http_transport
                logger.info(f"Created new transport with session ID: {new_session_id}")

                # Define the server runner
                async def run_server(*, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
                    async with http_transport.connect() as streams:
                        read_stream, write_stream = streams
                        task_status.started()
                        try:
                            # Use a cancel scope for idle timeout — when the
                            # deadline passes the scope cancels the loop and
                            # execution continues after the ``with`` block.
                            # Incoming requests push the deadline forward.
                            idle_scope = anyio.CancelScope()
                            if self.session_idle_timeout is not None:
                                idle_scope.deadline = anyio.current_time() + self.session_idle_timeout
                                http_transport.idle_scope = idle_scope

                            with idle_scope:
                                # Drive via `serve_loop` (not `Server.run()`) so the
                                # manager's already-entered lifespan is reused
                                # rather than re-entered per session.
                                await serve_loop(
                                    self.app,
                                    read_stream,
                                    write_stream,
                                    lifespan_state=self._lifespan_state,
                                    session_id=http_transport.mcp_session_id,
                                )

                            if idle_scope.cancelled_caught:
                                assert http_transport.mcp_session_id is not None
                                logger.info(f"Session {http_transport.mcp_session_id} idle timeout")
                                self._server_instances.pop(http_transport.mcp_session_id, None)
                                self._session_owners.pop(http_transport.mcp_session_id, None)
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
                                self._session_owners.pop(http_transport.mcp_session_id, None)

                # Assert task group is not None for type checking
                assert self._task_group is not None
                # Start the server task
                await self._task_group.start(run_server)

                # Handle the HTTP request and return the response
                await http_transport.handle_request(scope, receive, send)
        else:
            # Unknown or expired session ID - return 404 per MCP spec
            # TODO(L62): Align error code once spec clarifies
            # See: https://github.com/modelcontextprotocol/python-sdk/issues/1821
            logger.info(f"Rejected request with unknown or expired session ID: {request_mcp_session_id[:64]}")
            body = JSONRPCError(
                jsonrpc="2.0", id=None, error=ErrorData(code=INVALID_REQUEST, message="Session not found")
            )
            response = Response(
                body.model_dump_json(by_alias=True, exclude_unset=True), status_code=404, media_type="application/json"
            )
            await response(scope, receive, send)


class RequestBodyLimitMiddleware:
    """Reject oversized HTTP request bodies before invoking an ASGI application."""

    def __init__(self, app: ASGIApp, max_body_size: int) -> None:
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                pass
            else:
                if declared_size > self.max_body_size:
                    response = Response("Request body too large", status_code=413)
                    return await response(scope, receive, send)

        cached_messages: deque[Message] = deque()
        received_size = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                cached_messages.append(message)
                break

            received_size += len(message.get("body", b""))
            if received_size > self.max_body_size:
                response = Response("Request body too large", status_code=413)
                return await response(scope, receive, send)
            cached_messages.append(message)
            if not message.get("more_body", False):
                break

        async def replay() -> Message:
            if cached_messages:
                return cached_messages.popleft()
            return await receive()

        await self.app(scope, replay, send)


class StreamableHTTPASGIApp:
    """ASGI application for Streamable HTTP server transport."""

    def __init__(self, session_manager: StreamableHTTPSessionManager):
        self.session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.session_manager.asgi_app(scope, receive, send)
