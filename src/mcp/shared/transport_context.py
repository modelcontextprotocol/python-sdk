"""Transport-specific metadata attached to each inbound message.

`TransportContext` is the base; each transport defines its own subclass with
whatever fields make sense (HTTP request id, ASGI scope, stdio process handle,
etc.). The dispatcher passes it through opaquely; only the layers above the
dispatcher (`ServerRunner`, `Context`, user handlers) read its concrete fields.
"""

from collections.abc import Mapping
from dataclasses import dataclass

__all__ = ["TransportContext"]


@dataclass(kw_only=True, frozen=True)
class TransportContext:
    """Base transport metadata for an inbound message.

    Subclass per transport and add fields as needed. Instances are immutable.
    """

    kind: str
    """Short identifier for the transport (e.g. ``"stdio"``, ``"streamable-http"``)."""

    can_send_request: bool
    """Whether the transport can deliver server-initiated requests to the peer.

    ``False`` for stateless HTTP and HTTP with JSON response mode; ``True`` for
    stdio, SSE, and stateful streamable HTTP. When ``False``,
    `DispatchContext.send_raw_request` raises `NoBackChannelError`.
    """

    headers: Mapping[str, str] | None = None
    """Request headers carried by this message, when the transport has them.

    Populated by HTTP-based transports; ``None`` on stdio. Handlers should
    None-check before use.
    """
