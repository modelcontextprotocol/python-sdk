"""Request-scoped metadata and notifications for the native gRPC binding."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import anyio
from mcp.shared.dispatcher import CallOptions
from mcp.shared.exceptions import NoBackChannelError
from mcp.shared.transport import MessageMetadata, TransportContext
from mcp.types import RequestId


@dataclass(kw_only=True, frozen=True)
class GRPCContext(TransportContext):
    """gRPC peer information, including identities verified by the configured transport.

    Invocation metadata is untrusted. Peer identities are empty on insecure
    connections; the application decides which verified identities to authorize.
    """

    peer: str
    metadata: tuple[tuple[str, str | bytes], ...] = ()
    peer_identity_key: str | None = None
    peer_identities: tuple[bytes, ...] = ()


@dataclass
class GRPCDispatchContext:
    """Notifications are scoped to one RPC; server-initiated requests are unavailable."""

    transport: GRPCContext
    request_id: RequestId | None
    send_notification: Callable[[str, Mapping[str, Any] | None], Awaitable[None]]
    report_progress: bool = False
    message_metadata: MessageMetadata = None
    cancel_requested: anyio.Event = field(default_factory=anyio.Event)

    @property
    def can_send_request(self) -> bool:
        """The modern binding has no server-initiated request channel."""
        return False

    async def send_raw_request(
        self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None
    ) -> dict[str, Any]:
        """Reject requests on this request-scoped channel."""
        raise NoBackChannelError(method)

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        """Deliver a notification on the originating RPC."""
        await self.send_notification(method, params)

    async def progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        """Send progress only when the caller requested it."""
        if self.report_progress:
            params: dict[str, Any] = {"progressToken": self.request_id, "progress": progress}
            if total is not None:
                params["total"] = total
            if message is not None:
                params["message"] = message
            await self.notify("notifications/progress", params)
