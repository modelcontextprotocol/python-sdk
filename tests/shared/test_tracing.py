from __future__ import annotations

from typing import Any

import anyio
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from mcp import Client, types
from mcp.server.lowlevel.server import Server
from mcp.shared.exceptions import MCPError
from mcp.shared.tracing import ATTR_ERROR_TYPE, ATTR_MCP_METHOD_NAME

# Module-level provider + exporter — avoids the "Overriding of current
# TracerProvider is not allowed" warning that happens if you call
# set_tracer_provider() more than once.
_provider = TracerProvider()
_exporter = InMemorySpanExporter()
_provider.add_span_processor(SimpleSpanProcessor(_exporter))


@pytest.fixture(autouse=True)
def _otel_setup(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    """Patch the module-level tracer to use our test provider and clear spans between tests."""
    import mcp.shared.tracing as tracing_mod

    monkeypatch.setattr(tracing_mod, "_tracer", _provider.get_tracer("mcp"))
    _exporter.clear()
    return _exporter


@pytest.mark.anyio
async def test_span_created_on_send_request(_otel_setup: InMemorySpanExporter) -> None:
    """Verify a CLIENT span is created when send_request() succeeds."""
    exporter = _otel_setup

    server = Server(name="test server")
    async with Client(server) as client:
        await client.send_ping()

    spans = exporter.get_finished_spans()
    # Filter to only the CLIENT ping span (initialize also produces one, plus server spans)
    ping_spans = [
        s
        for s in spans
        if s.kind == SpanKind.CLIENT and s.attributes and s.attributes.get(ATTR_MCP_METHOD_NAME) == "ping"
    ]
    assert len(ping_spans) == 1

    span = ping_spans[0]
    assert span.name == "ping"
    assert span.kind == SpanKind.CLIENT
    assert span.status.status_code == StatusCode.OK


@pytest.mark.anyio
async def test_span_attributes_for_tool_call(_otel_setup: InMemorySpanExporter) -> None:
    """Verify span name includes tool name for tools/call requests."""
    exporter = _otel_setup

    server = Server(name="test server")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return [types.Tool(name="echo", description="Echo tool", input_schema={"type": "object"})]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent]:
        return [types.TextContent(type="text", text=str(arguments))]

    async with Client(server) as client:
        await client.call_tool("echo", {"msg": "hi"})

    spans = exporter.get_finished_spans()
    tool_spans = [
        s
        for s in spans
        if s.kind == SpanKind.CLIENT and s.attributes and s.attributes.get(ATTR_MCP_METHOD_NAME) == "tools/call"
    ]
    assert len(tool_spans) == 1

    span = tool_spans[0]
    assert span.name == "tools/call echo"
    assert span.status.status_code == StatusCode.OK


@pytest.mark.anyio
async def test_span_error_on_failure(_otel_setup: InMemorySpanExporter) -> None:
    """Verify span records ERROR status when the request times out."""
    exporter = _otel_setup

    server = Server(name="test server")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return [types.Tool(name="slow_tool", description="Slow", input_schema={"type": "object"})]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent]:
        await anyio.sleep(10)
        return []  # pragma: no cover

    async with Client(server) as client:
        with pytest.raises(MCPError, match="Timed out"):
            await client.session.send_request(
                types.CallToolRequest(params=types.CallToolRequestParams(name="slow_tool", arguments={})),
                types.CallToolResult,
                request_read_timeout_seconds=0.01,
            )

    spans = exporter.get_finished_spans()
    tool_spans = [
        s
        for s in spans
        if s.kind == SpanKind.CLIENT and s.attributes and s.attributes.get(ATTR_MCP_METHOD_NAME) == "tools/call"
    ]
    assert len(tool_spans) == 1

    span = tool_spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes is not None
    assert span.attributes.get(ATTR_ERROR_TYPE) == "MCPError"


@pytest.mark.anyio
async def test_no_span_for_excluded_method(_otel_setup: InMemorySpanExporter) -> None:
    """Verify no span is created for excluded methods (notifications/message)."""
    exporter = _otel_setup

    server = Server(name="test server")
    async with Client(server) as client:
        await client.send_ping()

    spans = exporter.get_finished_spans()
    excluded_spans = [
        s for s in spans if s.attributes and s.attributes.get(ATTR_MCP_METHOD_NAME) == "notifications/message"
    ]
    assert len(excluded_spans) == 0


@pytest.mark.anyio
async def test_server_span_on_successful_request(_otel_setup: InMemorySpanExporter) -> None:
    """Verify a SERVER span is created when the server handles a request."""
    exporter = _otel_setup

    server = Server(name="test server")
    async with Client(server) as client:
        await client.send_ping()

    spans = exporter.get_finished_spans()
    server_ping_spans = [
        s
        for s in spans
        if s.kind == SpanKind.SERVER and s.attributes and s.attributes.get(ATTR_MCP_METHOD_NAME) == "ping"
    ]
    assert len(server_ping_spans) == 1

    span = server_ping_spans[0]
    assert span.name == "ping"
    assert span.status.status_code == StatusCode.OK


@pytest.mark.anyio
async def test_server_span_includes_target(_otel_setup: InMemorySpanExporter) -> None:
    """Verify server span name includes tool name for tools/call requests."""
    exporter = _otel_setup

    server = Server(name="test server")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return [types.Tool(name="echo", description="Echo tool", input_schema={"type": "object"})]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent]:
        return [types.TextContent(type="text", text=str(arguments))]

    async with Client(server) as client:
        await client.call_tool("echo", {"msg": "hi"})

    spans = exporter.get_finished_spans()
    server_tool_spans = [
        s
        for s in spans
        if s.kind == SpanKind.SERVER and s.attributes and s.attributes.get(ATTR_MCP_METHOD_NAME) == "tools/call"
    ]
    assert len(server_tool_spans) == 1

    span = server_tool_spans[0]
    assert span.name == "tools/call echo"
    assert span.status.status_code == StatusCode.OK


@pytest.mark.anyio
async def test_server_span_error_on_error_response(_otel_setup: InMemorySpanExporter) -> None:
    """Verify server span records ERROR status when the server responds with ErrorData."""
    exporter = _otel_setup

    server = Server(name="test server")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        raise MCPError(code=-1, message="internal failure")

    async with Client(server) as client:
        with pytest.raises(MCPError, match="internal failure"):
            await client.list_tools()

    spans = exporter.get_finished_spans()
    server_spans = [
        s
        for s in spans
        if s.kind == SpanKind.SERVER and s.attributes and s.attributes.get(ATTR_MCP_METHOD_NAME) == "tools/list"
    ]
    assert len(server_spans) == 1

    span = server_spans[0]
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes is not None
    assert span.attributes.get(ATTR_ERROR_TYPE) == "MCPError"
