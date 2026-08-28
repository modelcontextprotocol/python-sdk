"""StreamableHTTP Session Manager for MCP servers."""

from __future__ import annotations

import contextlib
import logging
import math
from collections.abc import AsyncIterator
from typing import Any, Final
from uuid import uuid4

import anyio
from anyio.abc import TaskStatus
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser, AuthorizationContext, authorization_context
from mcp.server.lowlevel.server import Server as MCPServer
from mcp.server.streamable_http import (
    MCP_SESSION_ID_HEADER,
    EventStore,
    StreamableHTTPServerTransport,
)
from mcp.server.transport_security import (
    DEFAULT_MAX_REQUEST_BODY_SIZE,
    RequestBodyLimitMiddleware,
    TransportSecuritySettings,
)
from mcp.types import INTERNAL_ERROR, INVALID_REQUEST, ErrorData, JSONRPCError

__all__ = [
    "DEFAULT_MAX_REQUEST_BODY_SIZE",
    "DEFAULT_MAX_SESSIONS",
    "DEFAULT_SESSION_IDLE_TIMEOUT",
    "RequestBodyLimitMiddleware",
    "StreamableHTTPSessionManager",
]

logger = logging.getLogger(__name__)

DEFAULT_SESSION_IDLE_TIMEOUT: Final = 30 * 60
"""Default idle period in seconds after which a stateful Streamable HTTP session is closed (30 minutes)."""

DEFAULT_MAX_SESSIONS: Final = 10_000
"""Default maximum number of concurrent stateful Streamable HTTP sessions per session manager."""


class StreamableHTTPSessionManager:
    """
    Manages StreamableHTTP sessions with optional resumability via event store.

    This class abstracts away the complexity of session management, event storage,
    and request handling for StreamableHTTP transports. It handles:

    1. Session tracking for clients
    2. Resumability via an optional event store
    3. Connection management and lifecycle
    4. Request handling and transport setup
    5. Idle session cleanup

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
        session_idle_timeout: Idle timeout in seconds for stateful sessions. A session that has had no HTTP
            request in flight for this long (no request being served, no open GET stream) is terminated and
            removed; its ID then answers 404 and the client has to initialize a new session. When retry_interval
            is also configured, ensure the idle timeout comfortably exceeds the retry interval to avoid reaping
            sessions during normal SSE polling gaps. Defaults to 1800 (30 minutes); None disables the timeout so
            sessions live until the client deletes them or the manager shuts down. Unused in stateless mode.
        max_request_body_size: Maximum size in bytes for Streamable HTTP request bodies. Requests that
            exceed this limit receive a 413 response before parsing or session creation. Defaults to 4 MiB.
        max_sessions: Maximum number of concurrent stateful sessions. While that many sessions are open, a
            request that would open another one receives a 503 response; existing sessions are unaffected and
            room frees up as they end or expire. Defaults to 10 000; None removes the limit. Unused in stateless
            mode.
    """

    def __init__(
        self,
        app: MCPServer[Any, Any],
        event_store: EventStore | None = None,
        json_response: bool = False,
        stateless: bool = False,
        security_settings: TransportSecuritySettings | None = None,
        retry_interval: int | None = None,
        session_idle_timeout: float | None = DEFAULT_SESSION_IDLE_TIMEOUT,
        max_request_body_size: int = DEFAULT_MAX_REQUEST_BODY_SIZE,
        max_sessions: int | None = DEFAULT_MAX_SESSIONS,
    ):
        if session_idle_timeout is not None and not (math.isfinite(session_idle_timeout) and session_idle_timeout > 0):
            raise ValueError("session_idle_timeout must be a positive, finite number of seconds")
        if max_request_body_size <= 0:
            raise ValueError("max_request_body_size must be a positive number of bytes")
        if max_sessions is not None and max_sessions <= 0:
            raise ValueError("max_sessions must be a positive number of sessions or None")

        self.app = app
        self.event_store = event_store
        self.json_response = json_response
        self.stateless = stateless
        self.security_settings = security_settings
        self.retry_interval = retry_interval
        self.session_idle_timeout = session_idle_timeout
        self.max_request_body_size = max_request_body_size
        self.max_sessions = max_sessions
        self.asgi_app = RequestBodyLimitMiddleware(self._handle_request, max_request_body_size)

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
        await self.asgi_app(scope, receive, send)

    async def _handle_request(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
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

        # The per-request server task only ends once the transport is
        # terminated, so terminate it even if the request was cancelled.
        assert self._task_group is not None
        try:
            await self._task_group.start(run_stateless_server)
            await http_transport.handle_request(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
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
                await _error_response("Session not found", 404)(scope, receive, send)
                return
            logger.debug("Session already exists, handling request directly")
            await transport.handle_request(scope, receive, send)
            if transport.is_terminated:
                # The client ended the session (DELETE): forget it now rather
                # than when its server task winds down.
                await self._discard_session(request_mcp_session_id, transport)
            return

        if request_mcp_session_id is None:
            # New session case. Admission (the session limit and registration)
            # is decided under the lock; the request itself is served outside
            # it, so one client that is slow to send its opening request does
            # not hold up the others.
            async with self._session_creation_lock:
                http_transport = self._admit_session(requestor)
            if http_transport is None:
                logger.warning("Refusing to open a new session: %d sessions are already open", self.max_sessions)
                await _error_response("Too many open sessions", 503, INTERNAL_ERROR)(scope, receive, send)
                return
            await self._serve_opening_request(http_transport, scope, receive, send)
        else:
            # Unknown or expired session ID - return 404 per MCP spec
            await _error_response("Session not found", 404)(scope, receive, send)

    def _admit_session(self, requestor: AuthorizationContext | None) -> StreamableHTTPServerTransport | None:
        """Register a new session for `requestor` and return its transport, or None at the session limit."""
        if self.max_sessions is not None and len(self._server_instances) >= self.max_sessions:
            return None
        http_transport = StreamableHTTPServerTransport(
            mcp_session_id=uuid4().hex,
            is_json_response_enabled=self.json_response,
            event_store=self.event_store,  # May be None (no resumability)
            security_settings=self.security_settings,
            retry_interval=self.retry_interval,
            idle_timeout=self.session_idle_timeout,
        )
        session_id = http_transport.mcp_session_id
        assert session_id is not None
        if requestor is not None:
            self._session_owners[session_id] = requestor
        self._server_instances[session_id] = http_transport
        logger.info(f"Created new transport with session ID: {session_id}")
        return http_transport

    async def _serve_opening_request(
        self, http_transport: StreamableHTTPServerTransport, scope: Scope, receive: Receive, send: Send
    ) -> None:
        """Start the session's server task and let its transport answer the request that opens it.

        Without a session ID only an initialize request can succeed, so if this
        one is refused, fails or is cancelled (or the session's server task
        cannot even be started) nothing was established: the session is
        discarded again rather than kept (with its server task) around.
        """
        session_id = http_transport.mcp_session_id
        assert session_id is not None

        async def run_server(*, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
            async with http_transport.connect() as streams:
                read_stream, write_stream = streams
                task_status.started()
                try:
                    async with anyio.create_task_group() as session_tg:
                        if http_transport.idle_scope is not None:

                            async def end_when_idle(idle_scope: anyio.CancelScope) -> None:
                                # The transport cancels this scope once no request
                                # has been in flight for `session_idle_timeout`.
                                with idle_scope:
                                    await anyio.sleep_forever()
                                logger.info(f"Session {session_id} idle timeout")
                                # Discarding the session closes the transport's
                                # streams, so app.run() returns the way it does
                                # after a client DELETE and the server's lifespan
                                # for this session is torn down normally.
                                await self._discard_session(session_id, http_transport)

                            session_tg.start_soon(end_when_idle, http_transport.idle_scope)
                        await self.app.run(
                            read_stream,
                            write_stream,
                            self.app.create_initialization_options(),
                            stateless=False,
                        )
                        # The session ended some other way; stop waiting for it to go idle.
                        session_tg.cancel_scope.cancel()
                except Exception:
                    logger.exception(f"Session {session_id} crashed")
                finally:
                    # However the session ended (client DELETE, idle
                    # timeout, crash), discard it.
                    await self._discard_session(session_id, http_transport)

        established = False
        try:
            assert self._task_group is not None
            await self._task_group.start(run_server)
            status = await _send_and_report_status(http_transport.handle_request, scope, receive, send)
            established = status is not None and status < 400
        finally:
            if not established:  # pragma: no branch
                await self._discard_session(session_id, http_transport)

    async def _discard_session(self, session_id: str, transport: StreamableHTTPServerTransport) -> None:
        """Stop tracking the session and make sure its transport refuses anything that still reaches it.

        The session is forgotten first, before any await, so its ID answers 404
        from the moment this is called; terminating the transport is shielded so
        it completes even while the caller is being cancelled.
        """
        self._server_instances.pop(session_id, None)
        self._session_owners.pop(session_id, None)
        if not transport.is_terminated:
            with anyio.CancelScope(shield=True):
                await transport.terminate()


def _error_response(message: str, status_code: int, code: int = INVALID_REQUEST) -> Response:
    """A JSON-RPC error body (no usable request id) with the given HTTP status."""
    body = JSONRPCError(jsonrpc="2.0", id="server-error", error=ErrorData(code=code, message=message))
    return Response(
        body.model_dump_json(by_alias=True, exclude_none=True), status_code=status_code, media_type="application/json"
    )


async def _send_and_report_status(app: ASGIApp, scope: Scope, receive: Receive, send: Send) -> int | None:
    """Run `app` for one request and return the HTTP status it answered with (None if it sent no response)."""
    status: int | None = None

    async def watch_status(message: Message) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
        await send(message)

    await app(scope, receive, watch_status)
    return status
