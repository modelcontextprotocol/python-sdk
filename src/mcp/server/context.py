from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Protocol

from mcp_types import LoggingLevel, RequestId, RequestParamsMeta
from pydantic import BaseModel
from typing_extensions import TypeVar, deprecated

from mcp.server.connection import Connection
from mcp.server.session import ServerSession
from mcp.shared.context import BaseContext
from mcp.shared.dispatcher import DispatchContext
from mcp.shared.exceptions import MCPDeprecationWarning
from mcp.shared.message import CloseSSEStreamCallback
from mcp.shared.peer import Meta
from mcp.shared.transport_context import TransportContext

# Invariant: parametrizes a mutable dataclass field; dict default matches the default lifespan.
LifespanContextT = TypeVar("LifespanContextT", default=dict[str, Any])
RequestT = TypeVar("RequestT", default=Any)


@dataclass(kw_only=True)
class ServerRequestContext(Generic[LifespanContextT, RequestT]):
    """Per-request context handed to lowlevel request and notification handlers.

    Built by `ServerRunner._make_context`; carries the connection-scoped `ServerSession`,
    per-request metadata, and per-message transport data (the HTTP request, SSE stream-close callbacks).
    """

    session: ServerSession
    lifespan_context: LifespanContextT
    protocol_version: str
    method: str
    params: Mapping[str, Any] | None = None
    request_id: RequestId | None = None
    meta: RequestParamsMeta | None = None
    request: RequestT | None = None
    close_sse_stream: CloseSSEStreamCallback | None = None
    close_standalone_sse_stream: CloseSSEStreamCallback | None = None


# Covariant: `lifespan` is exposed read-only, so a `Context[AppState]` passes as `Context[object]`.
LifespanT_co = TypeVar("LifespanT_co", default=Any, covariant=True)


class Context(BaseContext[TransportContext], Generic[LifespanT_co]):
    """Server-side per-request context.

    Extends `BaseContext` with `lifespan`, `connection`, and request-scoped `log`. Not currently
    constructed by `ServerRunner`, which hands handlers a `ServerRequestContext` instead.
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
        """The per-client `Connection` this request belongs to."""
        return self._connection

    @property
    def session_id(self) -> str | None:
        """Convenience for `ctx.connection.session_id`; `None` on stdio and stateless HTTP."""
        return self._connection.session_id

    @property
    def headers(self) -> Mapping[str, str] | None:
        """Convenience for `ctx.transport.headers`; `None` on stdio."""
        return self.transport.headers

    @deprecated("The logging capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def log(self, level: LoggingLevel, data: Any, logger: str | None = None, *, meta: Meta | None = None) -> None:
        """Send a `notifications/message` log entry on this request's back-channel.

        Rides the request's SSE stream in streamable HTTP; `ctx.connection.log(...)` uses the standalone stream.
        """
        params: dict[str, Any] = {"level": level, "data": data}
        if logger is not None:
            params["logger"] = logger
        if meta:
            params["_meta"] = meta
        await self.notify("notifications/message", params)


HandlerResult = BaseModel | dict[str, Any] | None
"""What a request handler (or middleware) may return; `ServerRunner` serializes all three to a result dict."""

CallNext = Callable[["ServerRequestContext[Any, Any]"], Awaitable[HandlerResult]]
"""Invokes the rest of the chain; rewrite `method`/`params` via `dataclasses.replace(ctx, ...)` first."""

_MwLifespanT = TypeVar("_MwLifespanT")


class ServerMiddleware(Protocol[_MwLifespanT]):
    """Context-tier middleware: `(ctx, call_next) -> result`.

    Wraps every inbound request and notification before any validation, lookup, or handshake:
    `initialize`, the pre-init gate, `METHOD_NOT_FOUND`, params validation, the handler call, and
    `notifications/initialized` all run inside `call_next(ctx)`. `notifications/cancelled` is
    observed too; the dispatcher applies the cancellation itself, then forwards it. A request-side
    failure reaches the middleware as a raised `MCPError` (or `ValidationError` for malformed
    params). Listed outermost-first on `Server.middleware`.

    `ctx.method` and `ctx.params` are the raw inbound values (no model validation yet); to rewrite
    either, pass an adjusted context: `await call_next(replace(ctx, params=...))`.
    `ctx.request_id is None` distinguishes a notification, for which `call_next(ctx)` returns
    `None` and the middleware's own return value is discarded.

    !!! warning
        `initialize` is handled inline - the dispatcher reads no further inbound messages until
        the chain returns, so awaiting a server-to-client request (`ctx.session.send_request`,
        `send_ping`, ...) while handling `initialize` deadlocks the connection. Send-and-forget
        notifications are safe. `initialize` is observed but not rewritable: the post-chain
        handshake commit reads the wire params, so to veto the handshake raise *before*
        `call_next()`.

    `Server[L].middleware` holds `ServerMiddleware[L]`; `ServerRequestContext` is invariant in `L`,
    so reusable middleware should be typed `ServerMiddleware[Any]` to register on any `Server[L]`.
    """

    # TODO(maxisbey): once `_make_context` returns the covariant `Context[L]` again, restore
    # `contravariant=True` on `_MwLifespanT` and retype `ctx` below to `Context[_MwLifespanT]` so
    # reusable middleware can be `ServerMiddleware[object]` instead of `ServerMiddleware[Any]`.

    async def __call__(
        self,
        ctx: ServerRequestContext[_MwLifespanT, Any],
        call_next: CallNext,
    ) -> HandlerResult: ...
