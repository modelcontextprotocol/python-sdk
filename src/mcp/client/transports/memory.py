"""In-memory transport for testing MCP servers without network overhead."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp.server import Server
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage


class InMemoryTransport:
    """In-memory transport for testing MCP servers without network overhead.

    This transport starts the server in a background task and provides
    streams for client-side communication. The server is automatically
    stopped when the context manager exits.

    Example:
        ```python
        from mcp.client import Client
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("test")

        @server.tool()
        def add(a: int, b: int) -> int:
            return a + b

        # Direct usage with Client (recommended)
        async with Client(server) as client:
            result = await client.call_tool("add", {"a": 1, "b": 2})

        # Or explicit transport usage
        async with Client(InMemoryTransport(server)) as client:
            result = await client.call_tool("add", {"a": 1, "b": 2})
        ```
    """

    def __init__(
        self,
        server: Server[Any] | FastMCP,
        *,
        raise_exceptions: bool = False,
    ) -> None:
        """Initialize the in-memory transport.

        Args:
            server: The MCP server to connect to (Server or FastMCP instance).
            raise_exceptions: Whether to raise exceptions from the server.
        """
        self._server = server
        self._raise_exceptions = raise_exceptions

    @asynccontextmanager
    async def connect(
        self,
    ) -> AsyncIterator[
        tuple[
            MemoryObjectReceiveStream[SessionMessage | Exception],
            MemoryObjectSendStream[SessionMessage],
        ]
    ]:
        """Connect to the server and return streams for communication.

        Yields:
            A tuple of (read_stream, write_stream) for bidirectional communication.
        """
        # Unwrap FastMCP to get underlying Server
        actual_server: Server[Any]
        if isinstance(self._server, FastMCP):
            actual_server = self._server._mcp_server  # type: ignore[reportPrivateUsage]
        else:
            actual_server = self._server

        async with create_client_server_memory_streams() as (client_streams, server_streams):
            client_read, client_write = client_streams
            server_read, server_write = server_streams

            async with anyio.create_task_group() as tg:
                # Start server in background
                tg.start_soon(
                    lambda: actual_server.run(
                        server_read,
                        server_write,
                        actual_server.create_initialization_options(),
                        raise_exceptions=self._raise_exceptions,
                    )
                )

                try:
                    yield client_read, client_write
                finally:
                    tg.cancel_scope.cancel()
