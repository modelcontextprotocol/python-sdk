from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Protocol

from mcp_types import RequestId, RequestParamsMeta
from pydantic import BaseModel
from typing_extensions import TypeVar

from mcp.server.session import ServerSession
from mcp.shared.message import CloseSSEStreamCallback

# Invariant: parametrizes a mutable dataclass field; dict default matches the default lifespan.
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
    protocol_version: str
    method: str
    params: Mapping[str, Any] | None = None
    request_id: RequestId | None = None
    meta: RequestParamsMeta | None = None
    request: RequestT | None = None
    close_sse_stream: CloseSSEStreamCallback | None = None
    close_standalone_sse_stream: CloseSSEStreamCallback | None = None


HandlerResult = BaseModel | dict[str, Any] | None
"""What a request handler (or middleware) may return. `ServerRunner` serializes
all three to a result dict."""

CallNext = Callable[["ServerRequestContext[Any, Any]"], Awaitable[HandlerResult]]
"""Invokes the rest of the chain with the given context. What a context
rewrite (`dataclasses.replace(ctx, ...)`) can alter depends on the tier:
`ServerMiddleware` runs before params validation, so its rewrites change what
the handler is invoked with; an `Extension` interceptor runs after, so its
rewrites change only what the handler observes on `ctx`."""

_MwLifespanT = TypeVar("_MwLifespanT")


class ServerMiddleware(Protocol[_MwLifespanT]):
    """Context-tier middleware: `(ctx, call_next) -> result`.

    Runs at the top of `ServerRunner._on_request` / `_on_notify` after `ctx`
    is built but before any validation, lookup, or handshake. Wraps every
    inbound request and notification: `initialize`, the pre-init gate,
    `METHOD_NOT_FOUND`, params validation, the handler call, and
    `notifications/initialized` all run inside `call_next(ctx)`.
    `notifications/cancelled` is observed too; the dispatcher applies the
    cancellation itself, then forwards the notification. A request-side
    failure reaches the middleware as a raised `MCPError` (or
    `ValidationError` for malformed params) so observation/logging middleware
    can record it. Listed outermost-first on `Server.middleware`.

    The method and the raw inbound params are `ctx.method` and `ctx.params` (no
    model validation has happened yet). To rewrite either before the handler
    runs, pass an adjusted context: `await call_next(replace(ctx, params=...))`.
    `ctx.request_id is None` distinguishes a notification from a request. For
    notifications `call_next(ctx)` returns `None` (a dropped or unhandled
    notification also returns `None`) and the middleware's own return value is
    discarded.

    !!! warning
        `initialize` is handled inline - the dispatcher does not read
        further inbound messages until the middleware chain returns. Awaiting a
        server-to-client request (`ctx.session.send_request`, `send_ping`, ...)
        while handling `initialize` therefore deadlocks the connection: the
        response can never be dequeued. Send-and-forget notifications are safe.
        `initialize` is observed but not rewritable: the post-chain handshake
        commit reads the wire params, so to veto the handshake raise *before*
        `call_next()`.

    `Server[L].middleware` holds `ServerMiddleware[L]`, so an app-specific
    middleware sees `ctx.lifespan_context: L`. While the context is the
    mutable `ServerRequestContext` dataclass it is invariant in `L`, so a
    reusable middleware should be typed `ServerMiddleware[Any]` to register on
    any `Server[L]`.
    """

    # TODO(maxisbey): once `_make_context` returns the (covariant)
    # `mcp.server._context.Context[L]` again, restore `_MwLifespanT` to
    # `contravariant=True` and retype `ctx` below to `Context[_MwLifespanT]` so
    # reusable middleware can be `ServerMiddleware[object]` instead of
    # `ServerMiddleware[Any]`.

    async def __call__(
        self,
        ctx: ServerRequestContext[_MwLifespanT, Any],
        call_next: CallNext,
    ) -> HandlerResult: ...
