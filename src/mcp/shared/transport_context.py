"""Transport-specific metadata attached to each inbound message.

Each transport subclasses `TransportContext`; the dispatcher passes it through
opaquely — only `ServerRunner`, `Context`, and user handlers read concrete fields.
"""

from collections.abc import Mapping
from dataclasses import dataclass

__all__ = ["TransportContext"]


@dataclass(kw_only=True, frozen=True)
class TransportContext:
    """Base transport metadata for an inbound message."""

    kind: str
    """Short identifier for the transport (e.g. `"stdio"`, `"streamable-http"`)."""

    can_send_request: bool
    """Whether the transport can deliver server-initiated requests to the peer.

    `False` for stateless HTTP and HTTP with JSON response mode, where
    `DispatchContext.send_raw_request` raises `NoBackChannelError`.
    """

    headers: Mapping[str, str] | None = None
    """Request headers carried by this message; populated by HTTP-based transports, `None` on stdio."""
