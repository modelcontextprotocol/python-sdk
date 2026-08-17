"""Transport protocol for MCP clients."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Final, Protocol

from mcp.shared._stream_protocols import ReadStream, WriteStream
from mcp.shared.message import SessionMessage

__all__ = ["ReadStream", "WriteStream", "Transport", "TransportStreams"]

TransportStreams = tuple[ReadStream[SessionMessage | Exception], WriteStream[SessionMessage]]

# SDK-private signal emitted by StreamableHTTPTransport after a request with an
# established MCP session receives HTTP 404. It never crosses the wire.
SESSION_EXPIRED: Final = -32003
SESSION_EXPIRED_MARKER: Final = "mcp.client.session_expired"


class Transport(AbstractAsyncContextManager[TransportStreams], Protocol):
    """Protocol for MCP transports.

    A transport is an async context manager that yields read and write streams
    for bidirectional communication with an MCP server.
    """
