from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, Protocol

from pydantic import BaseModel
from typing_extensions import TypeVar

from mcp.server._typed_request import TypedServerRequestMixin
from mcp.server.connection import Connection
from mcp.server.experimental.request_context import Experimental
from mcp.server.session import ServerSession
from mcp.shared._context import RequestContext
from mcp.shared.context import BaseContext
from mcp.shared.dispatcher import DispatchContext
from mcp.shared.message import CloseSSEStreamCallback
from mcp.shared.peer import Meta, PeerMixin
from mcp.shared.transport_context import TransportContext
from mcp.types import LoggingLevel, RequestParamsMeta

LifespanContextT = TypeVar("LifespanContextT", default=dict[str, Any])
RequestT = TypeVar("RequestT", default=Any)


@dataclass(kw_only=True)
class ServerRequestContext(RequestContext[ServerSession], Generic[LifespanContextT, RequestT]):
    lifespan_context: LifespanContextT
    experimental: Experimental
    request: RequestT | None = None
    close_sse_stream: CloseSSEStreamCallback | None = None
    close_standalone_sse_stream: CloseSSEStreamCallback | None = None


LifespanT = TypeVar("LifespanT", default=Any, covariant=True)


class Context(BaseContext[TransportContext], PeerMixin, TypedServerRequestMixin, Generic[LifespanT]):
    """Server-side per-request context.

    Composes `BaseContext` (forwards to `DispatchContext`, satisfies `Outbound`),
    `PeerMixin` (kwarg-style ``sample``/``elicit_*``/``list_roots``/``ping``),
    and `TypedServerRequestMixin` (typed ``send_request(req) -> Result``). Adds
    ``lifespan`` and ``connection``.

    Constructed by `ServerRunner` per inbound request and handed to the user's
    handler.
    """

    def __init__(
        self,
        dctx: DispatchContext[TransportContext],
        *,
        lifespan: LifespanT,
        connection: Connection,
        meta: RequestParamsMeta | None = None,
    ) -> None:
        super().__init__(dctx, meta=meta)
        self._lifespan = lifespan
        self._connection = connection

    @property
    def lifespan(self) -> LifespanT:
        """The server-wide lifespan output (what `Server(..., lifespan=...)` yielded)."""
        return self._lifespan

    @property
    def connection(self) -> Connection:
        """The per-client `Connection` for this request's connection."""
        return self._connection

    async def log(self, level: LoggingLevel, data: Any, logger: str | None = None, *, meta: Meta | None = None) -> None:
        """Send a request-scoped ``notifications/message`` log entry.

        Uses this request's back-channel (so the entry rides the request's SSE
        stream in streamable HTTP), not the standalone stream — use
        ``ctx.connection.log(...)`` for that.
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

_MwLifespanT = TypeVar("_MwLifespanT", contravariant=True)


class ServerMiddleware(Protocol[_MwLifespanT]):
    """Context-tier middleware: ``(ctx, method, typed_params, call_next) -> result``.

    Runs *inside* `ServerRunner._on_request` after params validation and
    `Context` construction. Wraps registered handlers (including ``ping``) but
    not ``initialize``, ``METHOD_NOT_FOUND``, or validation failures. Listed
    outermost-first on `Server.middleware`.

    `Server[L].middleware` holds `ServerMiddleware[L]`, so an app-specific
    middleware sees `ctx.lifespan: L`. A reusable middleware can be typed
    `ServerMiddleware[object]` — `Context` is covariant in `LifespanT`, so it
    registers on any `Server[L]`.
    """

    async def __call__(
        self,
        ctx: Context[_MwLifespanT],
        method: str,
        params: BaseModel,
        call_next: CallNext,
    ) -> HandlerResult: ...
