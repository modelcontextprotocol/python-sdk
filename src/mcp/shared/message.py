"""Message wrapper with metadata support.

This module defines a wrapper type that combines JSONRPCMessage with metadata
to support transport-specific features like resumability.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from mcp_types import JSONRPCMessage, RequestId

ResumptionToken = str

ResumptionTokenUpdateCallback = Callable[[ResumptionToken], Awaitable[None]]


def extract_raw_request_id(raw_message: Any) -> RequestId | None:
    """Best-effort extraction of a JSON-RPC request id from an unvalidated payload.

    Used to correlate error responses with the originating request when an incoming
    message fails JSON-RPC envelope validation: even though the envelope is invalid,
    the ``id`` member is often still present in the raw parsed JSON.

    Args:
        raw_message: The parsed JSON payload, before any envelope validation.

    Returns:
        The request id when it is a valid JSON-RPC id type (a string, or an integer
        that is not a bool — ``bool`` subclasses ``int`` but is not a valid id),
        otherwise ``None``.
    """
    if isinstance(raw_message, dict):
        raw_id = cast("dict[Any, Any]", raw_message).get("id")
        if isinstance(raw_id, str) or (isinstance(raw_id, int) and not isinstance(raw_id, bool)):
            return raw_id
    return None


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
