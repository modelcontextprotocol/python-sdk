from __future__ import annotations

import json
from typing import Any, cast

import pytest
from logfire.testing import CaptureLogfire
from opentelemetry.sdk.metrics._internal.point import MetricsData

from mcp import types
from mcp.client.client import Client
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel.server import Server
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError

pytestmark = pytest.mark.anyio


def _get_mcp_metrics(capfire: CaptureLogfire) -> dict[str, Any]:
    """Return collected metrics whose name starts with 'mcp.', keyed by name."""
    exported = json.loads(cast(MetricsData, capfire.metrics_reader.get_metrics_data()).to_json())
    [resource_metric] = exported["resource_metrics"]
    all_metrics = [metric for scope_metric in resource_metric["scope_metrics"] for metric in scope_metric["metrics"]]
    return {m["name"]: m for m in all_metrics if m["name"].startswith("mcp.")}


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

    metrics = _get_mcp_metrics(capfire)

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
    assert tools_call_point["sum"] >= 0

    # tools/list is also called during initialization
    assert any(p["attributes"]["mcp.method.name"] == "tools/list" for p in op_points)

    session_metric = metrics["mcp.server.session.duration"]
    assert session_metric["unit"] == "s"
    [session_point] = session_metric["data"]["data_points"]
    assert session_point["attributes"]["mcp.protocol.version"] == "2025-11-25"
    assert "error.type" not in session_point["attributes"]
    assert session_point["count"] == 1
    assert session_point["sum"] >= 0


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
async def test_server_operation_error_metrics(capfire: CaptureLogfire):
    """Verify that error.type and rpc.response.status_code are set when a handler raises MCPError."""

    async def handle_call_tool(
        ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        raise MCPError(types.INVALID_PARAMS, "bad params")

    server = Server("test", on_call_tool=handle_call_tool)

    async with Client(server) as client:
        with pytest.raises(MCPError):
            await client.call_tool("boom", {})

    metrics = _get_mcp_metrics(capfire)
    op_points = metrics["mcp.server.operation.duration"]["data"]["data_points"]
    error_point = next(p for p in op_points if p["attributes"]["mcp.method.name"] == "tools/call")
    assert error_point["attributes"]["error.type"] == str(types.INVALID_PARAMS)
    assert error_point["attributes"]["rpc.response.status_code"] == str(types.INVALID_PARAMS)


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
async def test_server_session_error_metrics(capfire: CaptureLogfire):
    """Verify that error.type is set on session duration when the session exits with an exception."""

    async def handle_call_tool(
        ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        raise RuntimeError("unexpected crash")

    server = Server("test", on_call_tool=handle_call_tool)

    # raise_exceptions=True lets the RuntimeError escape the handler and crash the session,
    # simulating what happens in production when an unhandled exception exits the session block.
    with pytest.raises(Exception):
        async with Client(server, raise_exceptions=True) as client:
            await client.call_tool("boom", {})

    metrics = _get_mcp_metrics(capfire)
    session_points = metrics["mcp.server.session.duration"]["data"]["data_points"]
    error_session_points = [p for p in session_points if "error.type" in p["attributes"]]
    assert len(error_session_points) >= 1
    # anyio wraps task group exceptions in ExceptionGroup
    assert error_session_points[0]["attributes"]["error.type"] in ("RuntimeError", "ExceptionGroup")
