"""Wrapper pairing JSONRPCMessage with metadata for transport-specific features like resumability."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from mcp_types import JSONRPCMessage, RequestId

ResumptionToken = str

ResumptionTokenUpdateCallback = Callable[[ResumptionToken], Awaitable[None]]

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
    # Transport-specific request context (e.g. starlette Request for HTTP, None for stdio).
    # Typed as Any because the server layer is transport-agnostic.
    request_context: Any = None
    # Closes the current request's SSE connection without terminating its stream (client resumes via Last-Event-ID).
    close_sse_stream: CloseSSEStreamCallback | None = None
    # Closes the standalone GET SSE stream (unsolicited notifications).
    close_standalone_sse_stream: CloseSSEStreamCallback | None = None


MessageMetadata = ClientMessageMetadata | ServerMessageMetadata | None


@dataclass
class SessionMessage:
    """A JSON-RPC message paired with transport metadata."""

    message: JSONRPCMessage
    metadata: MessageMetadata = None
