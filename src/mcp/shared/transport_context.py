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
    """Short identifier for the transport (e.g. `"stdio"`, `"streamable-http"`)."""

    can_send_request: bool
    """Whether this message's request-scoped channel can deliver a server-initiated request.

    `False` for any of three reasons: the response has no room (streamable
    HTTP in JSON-response mode and the 2026-07-28 single-exchange entry answer
    with one JSON-RPC reply), the client's reply has nowhere to land (stateless
    HTTP, no session), or the protocol forbids server-initiated requests (any
    2026-07-28 connection, whose dispatch masks the flag off). `True` for a
    plain duplex pipe (stdio, SSE) and stateful streamable HTTP with SSE
    responses, all pre-2026-07-28. When `False`,
    `DispatchContext.send_raw_request` raises `NoBackChannelError` instead of
    parking a waiter no reply can reach. Says nothing about the connection's
    standalone channel, which refuses separately.
    """

    headers: Mapping[str, str] | None = None
    """Request headers carried by this message, when the transport has them.

    Populated by HTTP-based transports; `None` on stdio. Handlers should
    None-check before use.
    """
