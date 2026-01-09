"""Message wrapper with metadata support.

This module defines a wrapper type that combines JSONRPCMessage with metadata
to support transport-specific features like resumability.
"""

import contextvars
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from mcp.types import JSONRPCMessage, RequestId

ResumptionToken = str

ResumptionTokenUpdateCallback = Callable[[ResumptionToken], Awaitable[None]]

# Callback type for closing SSE streams without terminating
CloseSSEStreamCallback = Callable[[], Awaitable[None]]


@dataclass
class ClientMessageMetadata:
    """Metadata specific to client messages."""

    resumption_token: ResumptionToken | None = None
    on_resumption_token_update: Callable[[ResumptionToken], Awaitable[None]] | None = None


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
    context: contextvars.Context = field(default_factory=contextvars.copy_context)
    metadata: MessageMetadata = None
