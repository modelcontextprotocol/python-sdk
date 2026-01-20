"""Base transport protocol for MCP clients."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol, runtime_checkable

from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp.shared.message import SessionMessage


@runtime_checkable
class Transport(Protocol):
    """Protocol for MCP client transports.

    All transports must implement a connect() async context manager that yields
    a tuple of (read_stream, write_stream) for bidirectional communication.

    Example:
        ```python
        class MyTransport:
            @asynccontextmanager
            async def connect(self):
                # Set up connection...
                yield read_stream, write_stream
                # Clean up...
        ```
    """

    @asynccontextmanager
    async def connect(
        self,
    ) -> AsyncIterator[
        tuple[
            MemoryObjectReceiveStream[SessionMessage | Exception],
            MemoryObjectSendStream[SessionMessage],
        ]
    ]:
        """Connect to the server and yield streams for communication.

        Yields:
            A tuple of (read_stream, write_stream) for bidirectional communication.
        """
        ...
        yield  # type: ignore[misc]
