"""Tests for InMemoryTransport."""

import pytest

from mcp import Client
from mcp.client.transports import InMemoryTransport
from mcp.server import Server
from mcp.server.fastmcp import FastMCP
from mcp.types import Resource


@pytest.fixture
def simple_server() -> Server:
    """Create a simple MCP server for testing."""
    server = Server(name="test_server")

    # pragma: no cover - handler exists only to register a resource capability.
    # Transport tests verify stream creation, not handler invocation.
    @server.list_resources()
    async def handle_list_resources():  # pragma: no cover
        return [
            Resource(
                uri="memory://test",
                name="Test Resource",
                description="A test resource",
            )
        ]

    return server


@pytest.fixture
def fastmcp_server() -> FastMCP:
    """Create a FastMCP server for testing."""
    server = FastMCP("test")

    # pragma: no cover on handlers below - they exist only to register capabilities.
    # Transport tests verify stream creation and basic protocol, not handler invocation.
    @server.tool()
    def greet(name: str) -> str:  # pragma: no cover
        """Greet someone by name."""
        return f"Hello, {name}!"

    @server.resource("test://resource")
    def test_resource() -> str:  # pragma: no cover
        """A test resource."""
        return "Test content"

    return server


pytestmark = pytest.mark.anyio


async def test_with_server(simple_server: Server):
    """Test creating transport with a Server instance."""
    transport = InMemoryTransport(simple_server)
    async with transport.connect() as (read_stream, write_stream):
        assert read_stream is not None
        assert write_stream is not None


async def test_with_fastmcp(fastmcp_server: FastMCP):
    """Test creating transport with a FastMCP instance."""
    transport = InMemoryTransport(fastmcp_server)
    async with transport.connect() as (read_stream, write_stream):
        assert read_stream is not None
        assert write_stream is not None


async def test_server_is_running(fastmcp_server: FastMCP):
    """Test that the server is running and responding to requests."""
    async with Client(fastmcp_server) as client:
        assert client.server_capabilities is not None


async def test_list_tools(fastmcp_server: FastMCP):
    """Test listing tools through the transport."""
    async with Client(fastmcp_server) as client:
        tools_result = await client.list_tools()
        assert len(tools_result.tools) > 0
        tool_names = [t.name for t in tools_result.tools]
        assert "greet" in tool_names


async def test_call_tool(fastmcp_server: FastMCP):
    """Test calling a tool through the transport."""
    async with Client(fastmcp_server) as client:
        result = await client.call_tool("greet", {"name": "World"})
        assert result is not None
        assert len(result.content) > 0
        assert "Hello, World!" in str(result.content[0])


async def test_raise_exceptions(fastmcp_server: FastMCP):
    """Test that raise_exceptions parameter is passed through."""
    transport = InMemoryTransport(fastmcp_server, raise_exceptions=True)
    async with transport.connect() as (read_stream, _write_stream):
        assert read_stream is not None
