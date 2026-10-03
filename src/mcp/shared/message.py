"""Message wrapper with metadata support.

This module defines a wrapper type that combines JSONRPCMessage with metadata
to support transport-specific features like resumability.
"""

from collections.abc import Awaitable, Callable
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
    # Callback the dispatcher runs when this request settles without a response
    # (e.g. it was cancelled), for a transport whose wire must still end the
    # request even though no response is written.
    on_request_unanswered: Callable[[], Awaitable[None]] | None = None
    # The transport's verdict on whether this message's request-scoped channel
    # can deliver a server-initiated request (see
    # `TransportContext.can_send_request`); a transport that says nothing leaves
    # it True.
    can_send_request: bool = True


MessageMetadata = ClientMessageMetadata | ServerMessageMetadata | None


@dataclass
class SessionMessage:
    """A message with specific metadata for transport-specific features."""

    message: JSONRPCMessage
    metadata: MessageMetadata = None
