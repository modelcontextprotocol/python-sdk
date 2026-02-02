"""Tests for InMemoryTransport."""

from typing import Any

import pytest

import mcp.types as types
from mcp import Client
from mcp.client._memory import InMemoryTransport
from mcp.server import Server
from mcp.server.mcpserver import MCPServer
from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext
from mcp.types import Resource


@pytest.fixture
def simple_server() -> Server:
    """Create a simple MCP server for testing."""

    # pragma: no cover - handler exists only to register a resource capability.
    # Transport tests verify stream creation, not handler invocation.
    async def handle_list_resources(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListResourcesResult:  # pragma: no cover
        return types.ListResourcesResult(
            resources=[
                Resource(
                    uri="memory://test",
                    name="Test Resource",
                    description="A test resource",
                )
            ]
        )

    return Server(name="test_server", on_list_resources=handle_list_resources)


@pytest.fixture
def mcpserver_server() -> MCPServer:
    """Create an MCPServer server for testing."""
    server = MCPServer("test")

    @server.tool()
    def greet(name: str) -> str:
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
    async with transport as (read_stream, write_stream):
        assert read_stream is not None
        assert write_stream is not None


async def test_with_mcpserver(mcpserver_server: MCPServer):
    """Test creating transport with an MCPServer instance."""
    transport = InMemoryTransport(mcpserver_server)
    async with transport as (read_stream, write_stream):
        assert read_stream is not None
        assert write_stream is not None


async def test_server_is_running(mcpserver_server: MCPServer):
    """Test that the server is running and responding to requests."""
    async with Client(mcpserver_server) as client:
        assert client.server_capabilities is not None


async def test_list_tools(mcpserver_server: MCPServer):
    """Test listing tools through the transport."""
    async with Client(mcpserver_server) as client:
        tools_result = await client.list_tools()
        assert len(tools_result.tools) > 0
        tool_names = [t.name for t in tools_result.tools]
        assert "greet" in tool_names


async def test_call_tool(mcpserver_server: MCPServer):
    """Test calling a tool through the transport."""
    async with Client(mcpserver_server) as client:
        result = await client.call_tool("greet", {"name": "World"})
        assert result is not None
        assert len(result.content) > 0
        assert "Hello, World!" in str(result.content[0])


async def test_raise_exceptions(mcpserver_server: MCPServer):
    """Test that raise_exceptions parameter is passed through."""
    transport = InMemoryTransport(mcpserver_server, raise_exceptions=True)
    async with transport as (read_stream, _write_stream):
        assert read_stream is not None
