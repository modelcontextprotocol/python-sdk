"""`BaseContext` — the user-facing per-request context.

Composition over a `DispatchContext`: forwards the transport metadata, the
back-channel (`send_request`/`notify`), progress reporting, and the cancel
event. Adds `meta` (the inbound request's `_meta` field).

Satisfies `Outbound`, so `PeerMixin` works on it (the server-side `Context`
mixes that in directly). Shared between client and server: the server's
`Context` extends this with `lifespan`/`connection`; `ClientContext` is just an
alias.
"""

from collections.abc import Mapping
from typing import Any, Generic

import anyio
from typing_extensions import TypeVar

from mcp.shared.dispatcher import CallOptions, DispatchContext
from mcp.shared.transport_context import TransportContext
from mcp.types import RequestParamsMeta

__all__ = ["BaseContext"]

TransportT = TypeVar("TransportT", bound=TransportContext, default=TransportContext)


class BaseContext(Generic[TransportT]):
    """Per-request context wrapping a `DispatchContext`.

    `ServerRunner` (PR4) constructs one per inbound request and passes it to
    the user's handler.
    """

    def __init__(self, dctx: DispatchContext[TransportT], meta: RequestParamsMeta | None = None) -> None:
        self._dctx = dctx
        self._meta = meta

    @property
    def transport(self) -> TransportT:
        """Transport-specific metadata for this inbound request."""
        return self._dctx.transport

    @property
    def cancel_requested(self) -> anyio.Event:
        """Set when the peer sends ``notifications/cancelled`` for this request."""
        return self._dctx.cancel_requested

    @property
    def can_send_request(self) -> bool:
        """Whether the back-channel can deliver server-initiated requests."""
        return self._dctx.transport.can_send_request

    @property
    def meta(self) -> RequestParamsMeta | None:
        """The inbound request's ``_meta`` field, if present."""
        return self._meta

    async def send_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        """Send a request to the peer on the back-channel.

        Raises:
            MCPError: The peer responded with an error.
            NoBackChannelError: ``can_send_request`` is ``False``.
        """
        return await self._dctx.send_request(method, params, opts)

    async def notify(self, method: str, params: Mapping[str, Any] | None) -> None:
        """Send a notification to the peer on the back-channel."""
        await self._dctx.notify(method, params)

    async def report_progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        """Report progress for this request, if the peer supplied a progress token.

        A no-op when no token was supplied.
        """
        await self._dctx.progress(progress, total, message)
