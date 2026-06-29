from __future__ import annotations

import mcp_types as types
import pytest
from logfire.testing import CaptureLogfire

from mcp.client.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.shared._otel import extract_trace_context

pytestmark = pytest.mark.anyio


def test_extract_trace_context_degrades_to_no_parent_on_malformed_traceparent() -> None:
    """A non-string `traceparent` makes `extract()` raise; the helper must return `None`, not propagate."""
    assert extract_trace_context({"traceparent": 123}) is None


async def test_client_and_server_spans(capfire: CaptureLogfire):
    server = MCPServer("test")

    @server.tool()
    def greet(name: str) -> str:
        """Greet someone."""
        return f"Hello, {name}!"

    async with Client(server, mode="legacy") as client:
        result = await client.call_tool("greet", {"name": "World"})

    assert isinstance(result.content[0], types.TextContent)
    assert result.content[0].text == "Hello, World!"

    spans = capfire.exporter.exported_spans_as_dict()
    span_names = {s["name"] for s in spans}

    assert "MCP send tools/call greet" in span_names
    assert "tools/call greet" in span_names

    client_span = next(s for s in spans if s["name"] == "MCP send tools/call greet")
    server_span = next(s for s in spans if s["name"] == "tools/call greet")

    assert client_span["attributes"]["mcp.method.name"] == "tools/call"
    assert server_span["attributes"]["mcp.method.name"] == "tools/call"

    # Same trace id proves trace-context propagation from client to server.
    assert server_span["context"]["trace_id"] == client_span["context"]["trace_id"]
