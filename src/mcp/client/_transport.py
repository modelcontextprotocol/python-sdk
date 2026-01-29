"""Transport protocol for MCP clients."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp.shared.message import SessionMessage

TransportStreams = tuple[MemoryObjectReceiveStream[SessionMessage | Exception], MemoryObjectSendStream[SessionMessage]]


class Transport(AbstractAsyncContextManager[TransportStreams], Protocol):
    """Protocol for MCP transports.

    A transport is an async context manager that yields read and write streams
    for bidirectional communication with an MCP server.
    """
