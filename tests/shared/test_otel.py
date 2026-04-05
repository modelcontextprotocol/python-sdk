from __future__ import annotations

import pytest
from logfire.testing import CaptureLogfire

from mcp import types
from mcp.client.client import Client
from mcp.server.mcpserver import MCPServer

pytestmark = pytest.mark.anyio


# Logfire warns about propagated trace context by default (distributed_tracing=None).
# This is expected here since we're testing cross-boundary context propagation.
@pytest.mark.filterwarnings("ignore::RuntimeWarning")
async def test_client_and_server_instrumentation(capfire: CaptureLogfire):
    """Verify that calling a tool produces client and server spans and metrics with correct attributes."""
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

    assert client_span["attributes"]["mcp.method.name"] == "tools/call"
    assert server_span["attributes"]["mcp.method.name"] == "tools/call"

    # Server span should be in the same trace as the client span (context propagation).
    assert server_span["context"]["trace_id"] == client_span["context"]["trace_id"]

    metrics = {m["name"]: m for m in capfire.get_collected_metrics() if m["name"].startswith("mcp.")}

    assert "mcp.server.operation.duration" in metrics
    assert "mcp.server.session.duration" in metrics

    op_metric = metrics["mcp.server.operation.duration"]
    assert op_metric["unit"] == "s"
    op_points = op_metric["data"]["data_points"]

    # tools/call data point
    tools_call_point = next(p for p in op_points if p["attributes"]["mcp.method.name"] == "tools/call")
    assert tools_call_point["attributes"]["gen_ai.tool.name"] == "greet"
    assert tools_call_point["attributes"]["gen_ai.operation.name"] == "execute_tool"
    assert tools_call_point["attributes"]["mcp.protocol.version"] == "2025-11-25"
    assert tools_call_point["count"] == 1
    assert tools_call_point["sum"] > 0

    # tools/list is also called during initialization
    assert any(p["attributes"]["mcp.method.name"] == "tools/list" for p in op_points)

    session_metric = metrics["mcp.server.session.duration"]
    assert session_metric["unit"] == "s"
    [session_point] = session_metric["data"]["data_points"]
    assert session_point["attributes"]["mcp.protocol.version"] == "2025-11-25"
    assert session_point["count"] == 1
    assert session_point["sum"] > 0
