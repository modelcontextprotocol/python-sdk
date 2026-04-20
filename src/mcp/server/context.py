from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic

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


LifespanT = TypeVar("LifespanT", default=Any)
TransportT = TypeVar("TransportT", bound=TransportContext, default=TransportContext)


class Context(BaseContext[TransportT], PeerMixin, TypedServerRequestMixin, Generic[LifespanT, TransportT]):
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
        dctx: DispatchContext[TransportT],
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
