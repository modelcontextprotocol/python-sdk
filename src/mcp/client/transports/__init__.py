"""Transport implementations for MCP clients.

This module provides transport abstractions for connecting to MCP servers
using different protocols:

- InMemoryTransport: For testing servers without network overhead
- HttpTransport: For Streamable HTTP connections (recommended for HTTP)
- SSETransport: For legacy Server-Sent Events connections

Example:
    ```python
    from mcp.client import Client
    from mcp.client.transports import HttpTransport, SSETransport

    # Using Streamable HTTP (recommended)
    async with Client(HttpTransport("http://localhost:8000/mcp")) as client:
        result = await client.call_tool("my_tool", {...})

    # Using legacy SSE
    async with Client(SSETransport("http://localhost:8000/sse")) as client:
        result = await client.call_tool("my_tool", {...})
    ```
"""

from mcp.client.transports.base import Transport
from mcp.client.transports.http import HttpTransport
from mcp.client.transports.memory import InMemoryTransport
from mcp.client.transports.sse import SSETransport

__all__ = [
    "Transport",
    "HttpTransport",
    "InMemoryTransport",
    "SSETransport",
]
