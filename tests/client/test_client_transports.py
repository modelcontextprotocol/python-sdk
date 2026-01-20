"""Tests for Client with different transport types."""

import pytest

from mcp.client import Client
from mcp.client.transports import HttpTransport, InMemoryTransport, SSETransport
from mcp.server.fastmcp import FastMCP


@pytest.fixture
def test_server() -> FastMCP:
    """Create a simple test server."""
    server = FastMCP("test")

    @server.tool()
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    return server


pytestmark = pytest.mark.anyio


async def test_client_with_server_directly(test_server: FastMCP):
    """Test Client accepts a Server/FastMCP instance directly."""
    async with Client(test_server) as client:
        result = await client.call_tool("add", {"a": 1, "b": 2})
        assert "3" in str(result.content[0])


async def test_client_with_in_memory_transport(test_server: FastMCP):
    """Test Client accepts an InMemoryTransport instance."""
    transport = InMemoryTransport(test_server)
    async with Client(transport) as client:
        result = await client.call_tool("add", {"a": 5, "b": 7})
        assert "12" in str(result.content[0])


async def test_client_with_raise_exceptions(test_server: FastMCP):
    """Test that raise_exceptions is passed through for in-memory transport."""
    async with Client(test_server, raise_exceptions=True) as client:
        # If we got here without error, raise_exceptions was accepted
        assert client.server_capabilities is not None


# Note: The following tests verify type acceptance but don't make network calls
# since they would require a real server running.


def test_client_accepts_http_transport():
    """Test that Client constructor accepts HttpTransport."""
    transport = HttpTransport("http://localhost:8000/mcp")
    # Just verify it can be constructed - don't enter context manager
    client = Client(transport)
    assert client._target is transport


def test_client_accepts_sse_transport():
    """Test that Client constructor accepts SSETransport."""
    transport = SSETransport("http://localhost:8000/sse")
    # Just verify it can be constructed - don't enter context manager
    client = Client(transport)
    assert client._target is transport


def test_client_accepts_url_string():
    """Test that Client constructor accepts a URL string."""
    client = Client("http://localhost:8000/mcp")
    # URL string should be stored as the target
    assert client._target == "http://localhost:8000/mcp"


def test_client_with_http_transport_and_headers():
    """Test that HttpTransport with headers can be passed to Client."""
    transport = HttpTransport(
        "http://localhost:8000/mcp",
        headers={"Authorization": "Bearer token123"},
    )
    client = Client(transport)
    assert client._target is transport
    assert transport._headers == {"Authorization": "Bearer token123"}
