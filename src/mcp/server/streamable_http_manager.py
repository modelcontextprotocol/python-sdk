"""StreamableHTTP Session Manager for MCP servers."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import anyio
from anyio.abc import TaskStatus
from mcp_types import DEFAULT_NEGOTIATED_VERSION, INVALID_REQUEST, ErrorData, JSONRPCError
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from mcp.server._streamable_http_modern import handle_modern_request
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser, AuthorizationContext, authorization_context
from mcp.server.connection import Connection
from mcp.server.runner import serve_connection, serve_loop
from mcp.server.streamable_http import (
    MCP_SESSION_ID_HEADER,
    EventStore,
    StreamableHTTPServerTransport,
)
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared._compat import resync_tracer
from mcp.shared.inbound import MCP_PROTOCOL_VERSION_HEADER
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.transport_context import TransportContext

if TYPE_CHECKING:
    from mcp.server.lowlevel.server import Server

logger = logging.getLogger(__name__)


class StreamableHTTPSessionManager:
    """Manages StreamableHTTP sessions, transports, and optional resumability via event store.

    Create only one instance per application. An instance cannot be reused after
    its `run()` context exits — create a new one to restart.

    Args:
        app: The MCP server instance.
        event_store: Enables resumable connections (clients can reconnect and receive missed events).
            If None, sessions are still tracked but not resumable.
        json_response: Use JSON responses instead of SSE streams.
        stateless: Create a fresh transport per request with no session tracking or state persistence.
        security_settings: Optional transport security settings.
        retry_interval: Retry interval in milliseconds suggested to clients in the SSE retry field.
        session_idle_timeout: Seconds of HTTP inactivity after which a stateful session is terminated
            and removed. When retry_interval is set, must comfortably exceed it to avoid reaping sessions
            during normal SSE polling gaps. Default None (no timeout); 1800 (30 minutes) suits most deployments.
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

        self._session_creation_lock = anyio.Lock()
        self._server_instances: dict[str, StreamableHTTPServerTransport] = {}
        # Credential that created each session; subsequent requests must present the same one.
        self._session_owners: dict[str, AuthorizationContext] = {}

        self._task_group = None
        self._lifespan_state: Any = None
        self._run_lock = anyio.Lock()
        self._has_started = False

    @contextlib.asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        """Run the task group that owns all session operations.

        Can only be called once per instance; create a new instance to restart.
        Use it in the lifespan context manager of your Starlette app:

        @contextlib.asynccontextmanager
        async def lifespan(app: Starlette) -> AsyncIterator[None]:
            async with session_manager.run():
                yield
        """
        async with self._run_lock:
            if self._has_started:
                raise RuntimeError(
                    "StreamableHTTPSessionManager .run() can only be called "
                    "once per instance. Create a new instance if you need to run again."
                )
            self._has_started = True

        async with self.app.lifespan(self.app) as lifespan_state, anyio.create_task_group() as tg:
            # Lifespan is entered once for the manager's lifetime, not per request;
            # per-connection cleanup belongs on `connection.exit_stack`.
            self._lifespan_state = lifespan_state
            self._task_group = tg
            logger.info("StreamableHTTP session manager started")
            try:
                yield
            finally:
                logger.info("StreamableHTTP session manager shutting down")
                tg.cancel_scope.cancel()
                self._task_group = None
                self._lifespan_state = None
                self._server_instances.clear()
                self._session_owners.clear()
        await resync_tracer()

    async def handle_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process an ASGI request, dispatching by protocol era and stateless mode."""
        if self._task_group is None:
            raise RuntimeError("Task group is not initialized. Make sure to use run().")

        # TODO(L49): header-only era routing; body-primary classification is a follow-up.
        # Legacy paths own only the known initialize-handshake versions; anything else
        # goes to the modern entry so the classifier can validate it and reject it structurally.
        header = MCP_PROTOCOL_VERSION_HEADER.encode("ascii")
        pv = next((v.decode("latin-1") for k, v in scope["headers"] if k == header), None)
        if pv is not None and pv not in HANDSHAKE_PROTOCOL_VERSIONS:
            await handle_modern_request(
                self.app, self.security_settings, self.json_response, self._lifespan_state, scope, receive, send
            )
            return

        if self.stateless:
            await self._handle_stateless_request(pv, scope, receive, send)
        else:
            await self._handle_stateful_request(scope, receive, send)

    async def _handle_stateless_request(
        self, protocol_version_hint: str | None, scope: Scope, receive: Receive, send: Send
    ) -> None:
        """Process request in stateless mode, creating a new transport for each request."""
        logger.debug("Stateless mode: Creating new transport for this request")
        http_transport = StreamableHTTPServerTransport(
            mcp_session_id=None,
            is_json_response_enabled=self.json_response,
            event_store=None,
            security_settings=self.security_settings,
        )

        async def run_stateless_server(*, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED):
            async with http_transport.connect() as streams:
                read_stream, write_stream = streams
                task_status.started()
                dispatcher: JSONRPCDispatcher[TransportContext] = JSONRPCDispatcher(
                    read_stream,
                    write_stream,
                    inline_methods=frozenset({"initialize"}),
                    # Without a session ID a server-to-client request could be written to this POST's
                    # response stream, but the client's reply has nowhere to land — `can_send_request=False`
                    # raises `NoBackChannelError` for requests while still allowing notifications.
                    transport_builder=lambda _md: TransportContext(kind="streamable-http", can_send_request=False),
                )
                # Born-ready: the legacy stateless path never opens a GET stream and need not see
                # `initialize`. The header (or the spec default when absent) seeds `ctx.protocol_version`.
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

        assert self._task_group is not None
        await self._task_group.start(run_stateless_server)

        await http_transport.handle_request(scope, receive, send)

        await http_transport.terminate()

    async def _handle_stateful_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process request in stateful mode, maintaining session state between requests."""
        request = Request(scope, receive)
        request_mcp_session_id = request.headers.get(MCP_SESSION_ID_HEADER)

        user = scope.get("user")
        requestor = authorization_context(user) if isinstance(user, AuthenticatedUser) else None

        if request_mcp_session_id is not None and request_mcp_session_id in self._server_instances:
            transport = self._server_instances[request_mcp_session_id]
            if requestor != self._session_owners.get(request_mcp_session_id):
                # Sessions are bound to the creating credential; respond as if the session did not exist.
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
            if transport.idle_scope is not None and self.session_idle_timeout is not None:
                transport.idle_scope.deadline = anyio.current_time() + self.session_idle_timeout  # pragma: no cover
            await transport.handle_request(scope, receive, send)
            return

        if request_mcp_session_id is None:
            logger.debug("Creating new transport")
            async with self._session_creation_lock:
                new_session_id = uuid4().hex
                http_transport = StreamableHTTPServerTransport(
                    mcp_session_id=new_session_id,
                    is_json_response_enabled=self.json_response,
                    event_store=self.event_store,
                    security_settings=self.security_settings,
                    retry_interval=self.retry_interval,
                )

                assert http_transport.mcp_session_id is not None
                if requestor is not None:
                    self._session_owners[http_transport.mcp_session_id] = requestor
                self._server_instances[http_transport.mcp_session_id] = http_transport
                logger.info(f"Created new transport with session ID: {new_session_id}")

                async def run_server(*, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
                    async with http_transport.connect() as streams:
                        read_stream, write_stream = streams
                        task_status.started()
                        try:
                            # Idle timeout: when the deadline passes the scope cancels the loop and execution
                            # resumes after the `with` block. Incoming requests push the deadline forward.
                            idle_scope = anyio.CancelScope()
                            if self.session_idle_timeout is not None:
                                idle_scope.deadline = anyio.current_time() + self.session_idle_timeout
                                http_transport.idle_scope = idle_scope

                            with idle_scope:
                                # `serve_loop` (not `Server.run()`) reuses the manager's already-entered
                                # lifespan rather than re-entering it per session.
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

                assert self._task_group is not None
                await self._task_group.start(run_server)

                await http_transport.handle_request(scope, receive, send)
        else:
            # Unknown or expired session ID: 404 per MCP spec. TODO(L62): align error code
            # once spec clarifies — https://github.com/modelcontextprotocol/python-sdk/issues/1821
            logger.info(f"Rejected request with unknown or expired session ID: {request_mcp_session_id[:64]}")
            body = JSONRPCError(
                jsonrpc="2.0", id=None, error=ErrorData(code=INVALID_REQUEST, message="Session not found")
            )
            response = Response(
                body.model_dump_json(by_alias=True, exclude_unset=True), status_code=404, media_type="application/json"
            )
            await response(scope, receive, send)


class StreamableHTTPASGIApp:
    """ASGI application for Streamable HTTP server transport."""

    def __init__(self, session_manager: StreamableHTTPSessionManager):
        self.session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.session_manager.handle_request(scope, receive, send)
