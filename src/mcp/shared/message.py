"""Message wrapper with metadata support.

This module defines a wrapper type that combines JSONRPCMessage with metadata
to support transport-specific features like resumability.
"""

from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from mcp_types import JSONRPCMessage, RequestId

ResumptionToken = str

ResumptionTokenUpdateCallback = Callable[[ResumptionToken], Awaitable[None]]

# Callback type for closing SSE streams without terminating
CloseSSEStreamCallback = Callable[[], Awaitable[None]]


@dataclass
class ClientMessageMetadata:
    """Metadata specific to client messages."""

    resumption_token: ResumptionToken | None = None
    on_resumption_token_update: Callable[[ResumptionToken], Awaitable[None]] | None = None
    # Per-message HTTP headers (e.g. MCP-Protocol-Version, Mcp-Method) the transport should set.
    headers: dict[str, str] | None = None


@dataclass
class ServerMessageMetadata:
    """Metadata specific to server messages."""

    related_request_id: RequestId | None = None
    # Transport-specific request context (e.g. starlette Request for HTTP
    # transports, None for stdio). Typed as Any because the server layer is
    # transport-agnostic.
    request_context: Any = None
    # Callback to close SSE stream for the current request without terminating
    close_sse_stream: CloseSSEStreamCallback | None = None
    # Callback to close the standalone GET SSE stream (for unsolicited notifications)
    close_standalone_sse_stream: CloseSSEStreamCallback | None = None


MessageMetadata = ClientMessageMetadata | ServerMessageMetadata | None


@dataclass
class SessionMessage:
    """A message with specific metadata for transport-specific features."""

    message: JSONRPCMessage
    metadata: MessageMetadata = None


@dataclass(slots=True, frozen=True)
class RequestSettled:
    """An inbound request finished without any JSON-RPC reply being written.

    Emitted by the dispatcher (only) when a peer cancellation interrupted the
    handler — the spec says receivers SHOULD NOT respond to a cancelled
    request. Transport-internal: transports with per-request resources (the
    legacy streamable-HTTP per-POST stream) consume it to end the exchange;
    serializing transports strip it via `wire_messages`. It is never put on
    any wire.
    """

    request_id: RequestId


async def wire_messages(
    stream: AsyncIterable[SessionMessage | RequestSettled],
) -> AsyncIterator[SessionMessage]:
    """Yield only serializable frames, stripping dispatcher lifecycle markers."""
    async for item in stream:
        if isinstance(item, RequestSettled):
            continue
        yield item
