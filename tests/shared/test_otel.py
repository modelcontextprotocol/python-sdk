from __future__ import annotations

import pytest
from logfire.testing import CaptureLogfire

from mcp import types
from mcp.client.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.shared._otel import build_span_attributes

pytestmark = pytest.mark.anyio


def test_build_span_attributes_ref_uri() -> None:
    """build_span_attributes extracts mcp.resource.uri from nested ref.uri."""
    attrs = build_span_attributes(
        "completion/complete",
        "1",
        params={"ref": {"uri": "test://doc"}},
    )
    assert attrs["mcp.resource.uri"] == "test://doc"
    assert "gen_ai.operation.name" not in attrs


def test_build_span_attributes_tools_call_no_name() -> None:
    """tools/call without a name param omits gen_ai.tool.name."""
    attrs = build_span_attributes("tools/call", "1", params={})
    assert attrs["gen_ai.operation.name"] == "execute_tool"
    assert "gen_ai.tool.name" not in attrs


def test_build_span_attributes_prompts_get_no_name() -> None:
    """prompts/get without a name param omits gen_ai.prompt.name."""
    attrs = build_span_attributes("prompts/get", "1", params={})
    assert "gen_ai.prompt.name" not in attrs
    assert "gen_ai.operation.name" not in attrs


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

    # GenAI semconv attributes — execute_tool only on tools/call
    assert client_span["attributes"]["gen_ai.operation.name"] == "execute_tool"
    assert client_span["attributes"]["gen_ai.tool.name"] == "greet"
    assert server_span["attributes"]["gen_ai.operation.name"] == "execute_tool"
    assert server_span["attributes"]["gen_ai.tool.name"] == "greet"

    # Server span should be in the same trace as the client span (context propagation).
    assert server_span["context"]["trace_id"] == client_span["context"]["trace_id"]


async def test_list_tools_spans(capfire: CaptureLogfire):
    """Verify that listing tools produces spans without gen_ai.operation.name."""
    server = MCPServer("test")

    async with Client(server) as client:
        await client.list_tools()

    spans = capfire.exporter.exported_spans_as_dict()

    client_span = next(s for s in spans if s["name"] == "MCP send tools/list")
    server_span = next(s for s in spans if s["name"] == "MCP handle tools/list")

    # gen_ai.operation.name SHOULD NOT be set for non-tool-call methods per spec
    assert "gen_ai.operation.name" not in client_span["attributes"]
    assert "gen_ai.operation.name" not in server_span["attributes"]
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

    assert client_span["attributes"]["mcp.resource.uri"] == "test://greeting"
    assert server_span["attributes"]["mcp.resource.uri"] == "test://greeting"
    # gen_ai.operation.name SHOULD NOT be set for resources/read per spec
    assert "gen_ai.operation.name" not in client_span["attributes"]
    assert "gen_ai.operation.name" not in server_span["attributes"]

    assert server_span["context"]["trace_id"] == client_span["context"]["trace_id"]


async def test_prompt_get_spans(capfire: CaptureLogfire):
    """Verify that getting a prompt produces spans with gen_ai.prompt.name."""
    server = MCPServer("test")

    @server.prompt()
    def summarize() -> str:
        """Summarize text."""
        return "Summarize the following: "

    async with Client(server) as client:
        await client.get_prompt("summarize", {})

    spans = capfire.exporter.exported_spans_as_dict()

    client_span = next(s for s in spans if s["name"] == "MCP send prompts/get summarize")
    server_span = next(s for s in spans if s["name"] == "MCP handle prompts/get summarize")

    assert client_span["attributes"]["gen_ai.prompt.name"] == "summarize"
    assert server_span["attributes"]["gen_ai.prompt.name"] == "summarize"
    # gen_ai.operation.name SHOULD NOT be set for prompts/get per spec
    assert "gen_ai.operation.name" not in client_span["attributes"]
    assert "gen_ai.operation.name" not in server_span["attributes"]

    assert server_span["context"]["trace_id"] == client_span["context"]["trace_id"]
