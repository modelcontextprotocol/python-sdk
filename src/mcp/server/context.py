from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, cast

from pydantic import BaseModel
from typing_extensions import TypeVar

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.connection import Connection
from mcp.server.session import ServerSession
from mcp.shared.context import BaseContext
from mcp.shared.dispatcher import DispatchContext
from mcp.shared.message import CloseSSEStreamCallback
from mcp.shared.peer import Meta
from mcp.shared.transport_context import TransportContext
from mcp.types import LoggingLevel, RequestId, RequestParamsMeta

# Invariant: parameterizes a mutable dataclass field; dict default matches the default lifespan.
LifespanContextT = TypeVar("LifespanContextT", default=dict[str, Any])
RequestT = TypeVar("RequestT", default=Any)


@dataclass(kw_only=True)
class ServerRequestContext(Generic[LifespanContextT, RequestT]):
    """Per-request context handed to lowlevel request and notification handlers.

    Built by `ServerRunner._make_context` for each inbound message. Carries the
    connection-scoped `ServerSession` (server-to-client requests and
    notifications), per-request metadata, and any per-message data the
    transport attached (the HTTP request, SSE stream-close callbacks).
    """

    session: ServerSession
    lifespan_context: LifespanContextT
    request_id: RequestId | None = None
    meta: RequestParamsMeta | None = None
    request: RequestT | None = None
    transport: TransportContext = field(
        default_factory=lambda: TransportContext(kind="unknown", can_send_request=False)
    )
    close_sse_stream: CloseSSEStreamCallback | None = None
    close_standalone_sse_stream: CloseSSEStreamCallback | None = None

    @property
    def session_id(self) -> str | None:
        """The transport's session id for this request, when one exists."""
        headers = self.headers
        if headers is not None:
            header_session_id = headers.get("mcp-session-id")
            if header_session_id is not None:
                return header_session_id
        query_params = getattr(self.request, "query_params", None)
        if query_params is None:
            return None
        return query_params.get("session_id") or query_params.get("sessionId")

    @property
    def headers(self) -> Mapping[str, str] | None:
        """Request headers carried by this message, when the transport has them.

        HTTP-based transports expose headers through their request object while
        direct/in-memory transports may provide them directly on the transport.
        """
        if self.transport.headers is not None:
            return self.transport.headers
        request_headers = getattr(self.request, "headers", None)
        if request_headers is None:
            return None
        return request_headers

    @property
    def access_token(self) -> AccessToken | None:
        """The OAuth access token for the current request, if authentication ran."""
        scope = getattr(self.request, "scope", None)
        typed_scope = cast("Mapping[str, object]", scope) if isinstance(scope, Mapping) else None
        user = typed_scope.get("user") if typed_scope is not None else None
        if isinstance(user, AuthenticatedUser):
            return user.access_token
        return get_access_token()


# Covariant: `lifespan` is exposed read-only, so a `Context[AppState]` passes as `Context[object]`.
LifespanT_co = TypeVar("LifespanT_co", default=Any, covariant=True)


class Context(BaseContext[TransportContext], Generic[LifespanT_co]):
    """Server-side per-request context.

    Extends `BaseContext` (transport metadata, the raw back-channel, progress
    reporting) with `lifespan`, `connection`, and request-scoped `log`.

    Not currently constructed by `ServerRunner`, which hands handlers a
    `ServerRequestContext` instead.
    """

    def __init__(
        self,
        dctx: DispatchContext[TransportContext],
        *,
        lifespan: LifespanT_co,
        connection: Connection,
        meta: RequestParamsMeta | None = None,
    ) -> None:
        super().__init__(dctx, meta=meta)
        self._lifespan = lifespan
        self._connection = connection

    @property
    def lifespan(self) -> LifespanT_co:
        """The server-wide lifespan output (what `Server(..., lifespan=...)` yielded)."""
        return self._lifespan

    @property
    def connection(self) -> Connection:
        """The per-client `Connection` for this request's connection."""
        return self._connection

    @property
    def session_id(self) -> str | None:
        """The transport's session id for this connection, when one exists.

        Convenience for `ctx.connection.session_id`. `None` on stdio and
        stateless HTTP.
        """
        return self._connection.session_id

    @property
    def headers(self) -> Mapping[str, str] | None:
        """Request headers carried by this message, when the transport has them.

        Convenience for `ctx.transport.headers`. `None` on stdio.
        """
        return self.transport.headers

    async def log(self, level: LoggingLevel, data: Any, logger: str | None = None, *, meta: Meta | None = None) -> None:
        """Send a request-scoped `notifications/message` log entry.

        Uses this request's back-channel (so the entry rides the request's SSE
        stream in streamable HTTP), not the standalone stream - use
        `ctx.connection.log(...)` for that.
        """
        params: dict[str, Any] = {"level": level, "data": data}
        if logger is not None:
            params["logger"] = logger
        if meta:
            params["_meta"] = meta
        await self.notify("notifications/message", params)


HandlerResult = BaseModel | dict[str, Any] | None
"""What a request handler (or middleware) may return. `ServerRunner` serializes
all three to a result dict."""

CallNext = Callable[[], Awaitable[HandlerResult]]

_MwLifespanT = TypeVar("_MwLifespanT")


class ServerMiddleware(Protocol[_MwLifespanT]):
    """Context-tier middleware: `(ctx, method, params, call_next) -> result`.

    Runs at the top of `ServerRunner._on_request` / `_on_notify` after `ctx`
    is built but before any validation, lookup, or handshake. Wraps every
    inbound request and notification: `initialize`, the pre-init gate,
    `METHOD_NOT_FOUND`, params validation, the handler call, and
    `notifications/initialized` all run inside `call_next()`.
    `notifications/cancelled` is observed too; the dispatcher applies the
    cancellation itself, then forwards the notification. A request-side
    failure reaches the middleware as a raised `MCPError` (or
    `ValidationError` for malformed params) so observation/logging middleware
    can record it. Listed outermost-first on `Server.middleware`.

    `ctx.request_id is None` distinguishes a notification from a request. For
    notifications `call_next()` returns `None` (a dropped or unhandled
    notification also returns `None`) and the middleware's own return value is
    discarded.

    `params` is the raw inbound mapping (no model validation has happened
    yet). For typed inspection, validate against the model the middleware
    expects.

    Warning: `initialize` is handled inline - the dispatcher does not read
    further inbound messages until the middleware chain returns. Awaiting a
    server-to-client request (`ctx.session.send_request`, `send_ping`, ...)
    while handling `initialize` therefore deadlocks the connection: the
    response can never be dequeued. Send-and-forget notifications are safe.

    `Server[L].middleware` holds `ServerMiddleware[L]`, so an app-specific
    middleware sees `ctx.lifespan_context: L`. While the context is the
    mutable `ServerRequestContext` dataclass it is invariant in `L`, so a
    reusable middleware should be typed `ServerMiddleware[Any]` to register on
    any `Server[L]`.
    """

    # TODO(maxisbey): once `_make_context` returns the (covariant) `Context[L]`
    # again, restore `_MwLifespanT` to `contravariant=True` and retype `ctx`
    # below to `Context[_MwLifespanT]` so reusable middleware can be
    # `ServerMiddleware[object]` instead of `ServerMiddleware[Any]`.

    async def __call__(
        self,
        ctx: ServerRequestContext[_MwLifespanT, Any],
        method: str,
        params: Mapping[str, Any] | None,
        call_next: CallNext,
    ) -> HandlerResult: ...
