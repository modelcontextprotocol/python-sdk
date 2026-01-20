"""Server-Sent Events (SSE) transport for MCP clients.

Note: SSE is a legacy transport. For new implementations, prefer HttpTransport
which uses the Streamable HTTP protocol.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp.client.sse import sse_client
from mcp.shared.message import SessionMessage


class SSETransport:
    """Server-Sent Events (SSE) transport for connecting to MCP servers.

    Note: SSE is a legacy transport. For new implementations, prefer
    HttpTransport which uses the Streamable HTTP protocol.

    Example:
        ```python
        from mcp.client import Client
        from mcp.client.transports import SSETransport

        async with Client(SSETransport("http://localhost:8000/sse")) as client:
            result = await client.call_tool("my_tool", {...})

        # With authentication
        transport = SSETransport(
            "http://localhost:8000/sse",
            headers={"Authorization": "Bearer token"},
        )
        async with Client(transport) as client:
            result = await client.call_tool("my_tool", {...})
        ```
    """

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, Any] | None = None,
        timeout: float = 5.0,
        sse_read_timeout: float = 300.0,
        auth: httpx.Auth | None = None,
        on_session_created: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize the SSE transport.

        Args:
            url: The SSE endpoint URL.
            headers: Optional headers to include in requests.
            timeout: HTTP timeout for regular operations (in seconds). Defaults to 5.0.
            sse_read_timeout: Timeout for SSE read operations (in seconds). Defaults to 300.0.
            auth: Optional HTTPX authentication handler.
            on_session_created: Optional callback invoked with the session ID when received.
        """
        self._url = url
        self._headers = headers
        self._timeout = timeout
        self._sse_read_timeout = sse_read_timeout
        self._auth = auth
        self._on_session_created = on_session_created

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
        async with sse_client(
            self._url,
            headers=self._headers,
            timeout=self._timeout,
            sse_read_timeout=self._sse_read_timeout,
            auth=self._auth,
            on_session_created=self._on_session_created,
        ) as (read_stream, write_stream):
            yield read_stream, write_stream
