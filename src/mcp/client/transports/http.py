"""Streamable HTTP transport for MCP clients."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp.client.streamable_http import streamable_http_client
from mcp.shared.message import SessionMessage


class HttpTransport:
    """Streamable HTTP transport for connecting to MCP servers over HTTP.

    This transport uses the Streamable HTTP protocol, which is the recommended
    transport for HTTP-based MCP connections.

    Example:
        ```python
        from mcp.client import Client
        from mcp.client.transports import HttpTransport

        # Basic usage
        async with Client(HttpTransport("http://localhost:8000/mcp")) as client:
            result = await client.call_tool("my_tool", {...})

        # Or use the convenience URL syntax
        async with Client("http://localhost:8000/mcp") as client:
            result = await client.call_tool("my_tool", {...})

        # With custom headers (e.g., authentication)
        transport = HttpTransport(
            "http://localhost:8000/mcp",
            headers={"Authorization": "Bearer token"},
        )
        async with Client(transport) as client:
            result = await client.call_tool("my_tool", {...})

        # With a pre-configured httpx client
        http_client = httpx.AsyncClient(
            headers={"Authorization": "Bearer token"},
            timeout=30.0,
        )
        transport = HttpTransport("http://localhost:8000/mcp", httpx_client=http_client)
        async with Client(transport) as client:
            result = await client.call_tool("my_tool", {...})
        ```
    """

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        httpx_client: httpx.AsyncClient | None = None,
        terminate_on_close: bool = True,
    ) -> None:
        """Initialize the HTTP transport.

        Args:
            url: The MCP server endpoint URL.
            headers: Optional headers to include in requests. For authentication,
                include an "Authorization" header or use httpx_client with auth
                configured. Ignored if httpx_client is provided.
            httpx_client: Optional pre-configured httpx.AsyncClient. If provided,
                the headers parameter is ignored. The client lifecycle is managed
                externally (not closed by this transport).
            terminate_on_close: If True, send a DELETE request to terminate the
                session when the context exits. Defaults to True.
        """
        self._url = url
        self._headers = headers
        self._httpx_client = httpx_client
        self._terminate_on_close = terminate_on_close

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
        # If headers are provided without a custom client, create one with those headers
        client = self._httpx_client
        if client is None and self._headers is not None:
            client = httpx.AsyncClient(headers=self._headers)

        async with streamable_http_client(
            self._url,
            http_client=client,
            terminate_on_close=self._terminate_on_close,
        ) as (read_stream, write_stream, _get_session_id):
            yield read_stream, write_stream
