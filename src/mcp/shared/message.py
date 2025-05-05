"""
Message wrapper with metadata support.

This module defines a wrapper type that combines JSONRPCMessage with metadata
to support transport-specific features like resumability.
"""

from collections.abc import Awaitable, Callable

from pydantic import BaseModel

from mcp.types import JSONRPCMessage, RequestId

ResumptionToken = str

ResumptionTokenUpdateCallback = Callable[[ResumptionToken], Awaitable[None]]


class ClientMessageMetadata(BaseModel):
    """Metadata specific to client messages."""

    resumption_token: ResumptionToken | None = None
    on_resumption_token_update: Callable[[ResumptionToken], Awaitable[None]] | None = (
        None
    )


class ServerMessageMetadata(BaseModel):
    """Metadata specific to server messages."""

    related_request_id: RequestId | None = None


MessageMetadata = ClientMessageMetadata | ServerMessageMetadata | None


class SessionMessage(BaseModel):
    """A message with specific metadata for transport-specific features."""

    message: JSONRPCMessage
    metadata: MessageMetadata = None
