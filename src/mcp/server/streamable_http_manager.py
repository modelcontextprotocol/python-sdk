"""StreamableHTTP Session Manager for MCP servers."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import anyio
from anyio.abc import TaskStatus
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser, AuthorizationContext, authorization_context
from mcp.server.lowlevel.server import Server as MCPServer
from mcp.server.streamable_http import (
    MCP_SESSION_ID_HEADER,
    EventStore,
    StreamableHTTPServerTransport,
)
from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings
from mcp.types import INVALID_REQUEST, ErrorData, JSONRPCError

logger = logging.getLogger(__name__)


class StreamableHTTPSessionManager:
    """
    Manages StreamableHTTP sessions with optional resumability via event store.

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
        app: MCPServer[Any, Any],
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

        # Pre-check middleware: the manager runs security validation *before*
        # deciding whether to allocate a session. Without this, a request that
        # fails security (DNS rebinding, bad Host) would either be rejected too
        # late (after a session has already been created and would leak) or with
        # the wrong status code (400 "Missing session ID" instead of 421
        # "Invalid Host header"). Using the same middleware the transport uses
        # keeps the two validation paths consistent.
        self._security = TransportSecurityMiddleware(security_settings)

        # Session tracking (only used if not stateless)
        self._session_creation_lock = anyio.Lock()
        self._server_instances: dict[str, StreamableHTTPServerTransport] = {}
        # Identity of the credential that created each session; requests for a
        # session must present the same credential.
        self._session_owners: dict[str, AuthorizationContext] = {}

        # The task group will be set during lifespan
        self._task_group = None
        # Thread-safe tracking of run() calls
        self._run_lock = anyio.Lock()
        self._has_started = False

    @contextlib.asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        """
        Run the session manager with proper lifecycle management.

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
                self._session_owners.clear()

    async def handle_request(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """
        Process ASGI request with proper session handling and transport setup.

        Dispatches to the appropriate handler based on stateless mode.

        Args:
            scope: ASGI scope
            receive: ASGI receive function
            send: ASGI send function
        """
        if self._task_group is None:
            raise RuntimeError("Task group is not initialized. Make sure to use run().")

        # Dispatch to the appropriate handler
        if self.stateless:
            await self._handle_stateless_request(scope, receive, send)
        else:
            await self._handle_stateful_request(scope, receive, send)

    async def _handle_stateless_request(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """
        Process request in stateless mode - creating a new transport for each request.

        Args:
            scope: ASGI scope
            receive: ASGI receive function
            send: ASGI send function
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
                except Exception:  # pragma: no cover
                    logger.exception("Stateless session crashed")

        # Assert task group is not None for type checking
        assert self._task_group is not None
        # Start the server task
        await self._task_group.start(run_stateless_server)

        # Handle the HTTP request and return the response
        await http_transport.handle_request(scope, receive, send)

        # Terminate the transport after the request is handled
        await http_transport.terminate()

    async def _handle_stateful_request(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """
        Process request in stateful mode - maintaining session state between requests.

        Args:
            scope: ASGI scope
            receive: ASGI receive function
            send: ASGI send function
        """
        request = Request(scope, receive)

        # Run security validation FIRST so DNS-rebinding / bad-Host requests
        # are rejected with 421 (or the transport-level Content-Type 400)
        # regardless of whether a session existed or not — and so bad-Host
        # requests can never trigger a session allocation.
        security_error = await self._security.validate_request(request, is_post=(request.method == "POST"))
        if security_error is not None:
            await security_error(scope, receive, send)
            return

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
                    jsonrpc="2.0", id="server-error", error=ErrorData(code=INVALID_REQUEST, message="Session not found")
                )
                response = Response(
                    body.model_dump_json(by_alias=True, exclude_none=True),
                    status_code=404,
                    media_type="application/json",
                )
                await response(scope, receive, send)
                return
            logger.debug("Session already exists, handling request directly")
            # Push back idle deadline on activity
            if transport.idle_scope is not None and self.session_idle_timeout is not None:  # pragma: no cover
                transport.idle_scope.deadline = anyio.current_time() + self.session_idle_timeout
            await transport.handle_request(scope, receive, send)
            return

        if request_mcp_session_id is None:
            # Only POST may initialize a new session (per MCP spec: a session is
            # opened by the response to the ``initialize`` JSON-RPC request,
            # which is always a POST). Any non-POST request without a session-id
            # is a protocol error and must be rejected here — the transport-layer
            # rejection happens too late: by the time
            # ``StreamableHTTPServerTransport.handle_request()`` sees the request,
            # a session has already been allocated in ``_server_instances`` and
            # a background ``run_server`` task has been spawned waiting on a
            # stream that will never receive anything. Both leak forever unless
            # ``session_idle_timeout`` is set (opt-in, off by default). Rejecting
            # here also holds for PUT/PATCH/OPTIONS/HEAD — the transport would
            # answer 405 to those, but only after the leaky allocation.
            if request.method != "POST":
                # GET/DELETE are protocol-valid methods when a session exists,
                # so the correct response for a missing session is 400 — matching
                # the transport's existing "Missing session ID" wording. Anything
                # else is a genuinely unsupported method, so 405 is more accurate.
                # Both branches mirror the shape produced by
                # ``StreamableHTTPServerTransport._create_error_response`` /
                # ``_handle_unsupported_request`` so clients see the same
                # JSON-RPC body and headers (including the RFC 7231 ``Allow``
                # advertisement for 405) whether the rejection happens here or
                # in the transport layer.
                if request.method in ("GET", "DELETE"):
                    error_body = JSONRPCError(
                        jsonrpc="2.0",
                        id="server-error",
                        error=ErrorData(code=INVALID_REQUEST, message="Bad Request: Missing session ID"),
                    )
                    response = Response(
                        content=error_body.model_dump_json(by_alias=True, exclude_none=True),
                        status_code=400,
                        media_type="application/json",
                    )
                else:
                    error_body = JSONRPCError(
                        jsonrpc="2.0",
                        id="server-error",
                        error=ErrorData(code=INVALID_REQUEST, message="Method Not Allowed"),
                    )
                    response = Response(
                        content=error_body.model_dump_json(by_alias=True, exclude_none=True),
                        status_code=405,
                        headers={
                            "Content-Type": "application/json",
                            "Allow": "GET, POST, DELETE",
                        },
                    )
                await response(scope, receive, send)
                return

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
                                    f"{http_transport.mcp_session_id} from "
                                    "active instances."
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
            body = JSONRPCError(
                jsonrpc="2.0", id="server-error", error=ErrorData(code=INVALID_REQUEST, message="Session not found")
            )
            response = Response(
                body.model_dump_json(by_alias=True, exclude_none=True), status_code=404, media_type="application/json"
            )
            await response(scope, receive, send)
