import logging
from collections.abc import Mapping
from typing import Any, Generic

from mcp_types import LoggingLevel, RequestParamsMeta
from typing_extensions import TypeVar, deprecated

from mcp.server.connection import Connection, allowed_log_levels
from mcp.shared.context import BaseContext
from mcp.shared.dispatcher import DispatchContext
from mcp.shared.exceptions import MCPDeprecationWarning
from mcp.shared.peer import Meta
from mcp.shared.transport_context import TransportContext

logger = logging.getLogger(__name__)
# `Context.log`'s `logger` parameter (the spec's logger-name field) shadows
# the module logger inside that method; this alias keeps it reachable there.
_logger = logger

# Covariant: `lifespan` is exposed read-only, so a `Context[AppState]` passes as `Context[object]`.
LifespanT_co = TypeVar("LifespanT_co", default=Any, covariant=True)


class Context(BaseContext[TransportContext], Generic[LifespanT_co]):
    """Server-side per-request context.

    Extends `BaseContext` (transport metadata, the raw back-channel, progress
    reporting) with `lifespan`, `connection`, and request-scoped `log`.

    Private for now: `ServerRunner` does not construct it, and hands handlers
    a `ServerRequestContext` (in `mcp.server.context`) instead.
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
        # Same per-request log gate as `ServerSession`: fixed at construction
        # from this request's `_meta` log-level opt-in and the connection's era.
        self._allowed_log_levels = allowed_log_levels(connection.protocol_version, meta)

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

    @deprecated("The logging capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def log(self, level: LoggingLevel, data: Any, logger: str | None = None, *, meta: Meta | None = None) -> None:
        """Send a request-scoped `notifications/message` log entry.

        Uses this request's back-channel (so the entry rides the request's SSE
        stream in streamable HTTP), not the standalone stream - use
        `ctx.connection.log(...)` for that.

        On 2026-07-28+ delivery is a per-request opt-in: nothing is sent
        unless this request's `_meta` carried the reserved log-level key, and
        entries below the requested level are dropped (debug-logged).
        Handshake versions send unconditionally, as before.
        """
        if level not in self._allowed_log_levels:
            _logger.debug("dropped notifications/message at %r: not opted in at that level on this request", level)
            return
        params: dict[str, Any] = {"level": level, "data": data}
        if logger is not None:
            params["logger"] = logger
        if meta:
            params["_meta"] = meta
        await self.notify("notifications/message", params)
