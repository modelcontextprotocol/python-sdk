from __future__ import annotations

import pytest
from logfire.testing import CaptureLogfire

from mcp import types
from mcp.client.client import Client
from mcp.server.mcpserver import MCPServer

pytestmark = pytest.mark.anyio


async def test_client_and_server_spans(capfire: CaptureLogfire):
    """Verify that calling a tool produces client and server spans with correct attributes."""
    server = MCPServer("test")

    @server.tool()
    def greet(name: str) -> str:
        """Greet someone."""
        return f"Hello, {name}!"

    async with Client(server) as client:
        result = await client.call_tool("greet", {"name": "World"})

    assert isinstance(result.content[0], types.TextContent)
    assert result.content[0].text == "Hello, World!"

    spans = capfire.exporter.exported_spans_as_dict()
    span_names = {s["name"] for s in spans}

    assert "MCP send tools/call greet" in span_names
    assert "MCP handle tools/call greet" in span_names

    client_span = next(s for s in spans if s["name"] == "MCP send tools/call greet")
    server_span = next(s for s in spans if s["name"] == "MCP handle tools/call greet")

    # Base RPC + MCP attributes
    assert client_span["attributes"]["rpc.system"] == "mcp"
    assert client_span["attributes"]["mcp.method.name"] == "tools/call"
    assert client_span["attributes"]["jsonrpc.request.id"] is not None
    assert server_span["attributes"]["rpc.system"] == "mcp"
    assert server_span["attributes"]["mcp.method.name"] == "tools/call"

    # GenAI semconv attributes
    assert client_span["attributes"]["gen_ai.operation.name"] == "execute_tool"
    assert client_span["attributes"]["gen_ai.tool.name"] == "greet"
    assert server_span["attributes"]["gen_ai.operation.name"] == "execute_tool"
    assert server_span["attributes"]["gen_ai.tool.name"] == "greet"

    # Server span should be in the same trace as the client span (context propagation).
    assert server_span["context"]["trace_id"] == client_span["context"]["trace_id"]


async def test_list_tools_spans(capfire: CaptureLogfire):
    """Verify that listing tools produces spans with list_tools operation."""
    server = MCPServer("test")

    @server.tool()
    def greet(name: str) -> str:
        """Greet someone."""
        return f"Hello, {name}!"

    async with Client(server) as client:
        await client.list_tools()

    spans = capfire.exporter.exported_spans_as_dict()

    client_span = next(s for s in spans if s["name"] == "MCP send tools/list")
    server_span = next(s for s in spans if s["name"] == "MCP handle tools/list")

    assert client_span["attributes"]["gen_ai.operation.name"] == "list_tools"
    assert server_span["attributes"]["gen_ai.operation.name"] == "list_tools"
    # No tool name on list — no specific tool targeted
    assert "gen_ai.tool.name" not in client_span["attributes"]
    assert "gen_ai.tool.name" not in server_span["attributes"]

    assert server_span["context"]["trace_id"] == client_span["context"]["trace_id"]


async def test_resource_read_spans(capfire: CaptureLogfire):
    """Verify that reading a resource produces spans with resource URI."""
    server = MCPServer("test")

    @server.resource("test://greeting")
    def greeting() -> str:
        return "hello"

    async with Client(server) as client:
        await client.read_resource("test://greeting")

    spans = capfire.exporter.exported_spans_as_dict()

    client_span = next(s for s in spans if s["name"] == "MCP send resources/read")
    server_span = next(s for s in spans if s["name"] == "MCP handle resources/read")

    assert client_span["attributes"]["gen_ai.operation.name"] == "read_resource"
    assert client_span["attributes"]["mcp.resource.uri"] == "test://greeting"
    assert server_span["attributes"]["gen_ai.operation.name"] == "read_resource"
    assert server_span["attributes"]["mcp.resource.uri"] == "test://greeting"

    assert server_span["context"]["trace_id"] == client_span["context"]["trace_id"]
