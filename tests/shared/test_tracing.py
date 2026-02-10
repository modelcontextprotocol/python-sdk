# pyright: reportMissingImports=false, reportUnknownVariableType=false
# pyright: reportUnknownMemberType=false, reportUnknownParameterType=false
# pyright: reportUnknownArgumentType=false
# opentelemetry-sdk does not ship type stubs, so we suppress unknown-type errors.
from __future__ import annotations

from typing import Any

import anyio
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from mcp import Client, types
from mcp.client.session import ClientSession
from mcp.server.lowlevel.server import Server
from mcp.shared.exceptions import MCPError
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from mcp.shared.tracing import (
    ATTR_ERROR_TYPE,
    ATTR_MCP_METHOD_NAME,
    _build_span_name,
    _extract_target,
)
from mcp.types import ErrorData, JSONRPCError, JSONRPCRequest

# Module-level provider + exporter — avoids the "Overriding of current
# TracerProvider is not allowed" warning that happens if you call
# set_tracer_provider() more than once.
_provider = TracerProvider()
_exporter = InMemorySpanExporter()
_provider.add_span_processor(SimpleSpanProcessor(_exporter))


@pytest.fixture(autouse=True)
def _otel_setup(monkeypatch: pytest.MonkeyPatch):
    """Patch the module-level tracer to use our test provider and clear spans between tests."""
    import mcp.shared.tracing as tracing_mod

    monkeypatch.setattr(tracing_mod, "_tracer", _provider.get_tracer("mcp"))
    _exporter.clear()
    yield _exporter


# --- Unit tests for helpers ---


@pytest.mark.parametrize(
    ("method", "params", "expected"),
    [
        ("tools/call", {"name": "my_tool"}, "my_tool"),
        ("prompts/get", {"name": "my_prompt"}, "my_prompt"),
        ("resources/read", {"uri": "file:///a.txt"}, "file:///a.txt"),
        ("ping", None, None),
        ("tools/call", {}, None),
        ("tools/call", {"name": 123}, None),
    ],
)
def test_extract_target(method: str, params: dict[str, Any] | None, expected: str | None) -> None:
    assert _extract_target(method, params) == expected


@pytest.mark.parametrize(
    ("method", "target", "expected"),
    [
        ("tools/call", "my_tool", "tools/call my_tool"),
        ("ping", None, "ping"),
    ],
)
def test_build_span_name(method: str, target: str | None, expected: str) -> None:
    assert _build_span_name(method, target) == expected


# --- Integration tests using real client/server ---


@pytest.mark.anyio
async def test_span_created_on_send_request(_otel_setup: InMemorySpanExporter) -> None:
    """Verify a CLIENT span is created when send_request() succeeds."""
    exporter = _otel_setup

    server = Server(name="test server")
    async with Client(server) as client:
        await client.send_ping()

    spans = exporter.get_finished_spans()
    # Filter to only the ping span (initialize also produces one)
    ping_spans = [s for s in spans if s.attributes and s.attributes.get(ATTR_MCP_METHOD_NAME) == "ping"]
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
    tool_spans = [s for s in spans if s.attributes and s.attributes.get(ATTR_MCP_METHOD_NAME) == "tools/call"]
    assert len(tool_spans) == 1

    span = tool_spans[0]
    assert span.name == "tools/call echo"
    assert span.status.status_code == StatusCode.OK


@pytest.mark.anyio
async def test_span_error_on_failure(_otel_setup: InMemorySpanExporter) -> None:
    """Verify span records ERROR status when the server returns a JSON-RPC error."""
    exporter = _otel_setup

    ev_done = anyio.Event()

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def mock_server():
            message = await server_read.receive()
            assert isinstance(message, SessionMessage)
            root = message.message
            assert isinstance(root, JSONRPCRequest)
            error_response = JSONRPCError(
                jsonrpc="2.0",
                id=root.id,
                error=ErrorData(code=-32600, message="Test error"),
            )
            await server_write.send(SessionMessage(message=error_response))

        async def make_request(session: ClientSession):
            with pytest.raises(MCPError):
                await session.send_request(types.PingRequest(), types.EmptyResult)
            ev_done.set()

        async with (
            anyio.create_task_group() as tg,
            ClientSession(read_stream=client_read, write_stream=client_write) as session,
        ):
            tg.start_soon(mock_server)
            tg.start_soon(make_request, session)
            with anyio.fail_after(2):  # pragma: no branch
                await ev_done.wait()

    spans = exporter.get_finished_spans()
    ping_spans = [s for s in spans if s.attributes and s.attributes.get(ATTR_MCP_METHOD_NAME) == "ping"]
    assert len(ping_spans) == 1

    span = ping_spans[0]
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
