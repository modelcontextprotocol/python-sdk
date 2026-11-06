from __future__ import annotations

import mcp_types as types
import pytest
from logfire.testing import CaptureLogfire
from opentelemetry.trace import StatusCode

from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.shared._otel import extract_trace_context
from mcp.shared.exceptions import MCPError

pytestmark = pytest.mark.anyio


def test_extract_trace_context_degrades_to_no_parent_on_malformed_traceparent() -> None:
    """A non-string `traceparent` makes `extract()` raise; the helper must return `None`, not propagate."""
    assert extract_trace_context({"traceparent": 123}) is None


async def test_client_and_server_spans(capfire: CaptureLogfire):
    """Verify that calling a tool produces client and server spans with correct attributes."""
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

    # Server span should be in the same trace as the client span (context propagation).
    assert server_span["context"]["trace_id"] == client_span["context"]["trace_id"]


async def test_client_span_records_error_status_when_peer_answers_with_jsonrpc_error(capfire: CaptureLogfire):
    """A request the peer answers with a JSON-RPC error ends its client span with status ERROR, the peer's
    message as the description, and the code in `error.type` and `rpc.response.status_code` (OpenTelemetry
    MCP semantic conventions, client span). A request that succeeds stays UNSET.
    """
    message = "unknown cursor"

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[])

    async def list_prompts(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListPromptsResult:
        raise MCPError(types.INVALID_PARAMS, message)

    server = Server("test", on_list_tools=list_tools, on_list_prompts=list_prompts)

    async with Client(server, mode="legacy") as client:
        await client.list_tools()
        with pytest.raises(MCPError) as exc_info:
            await client.list_prompts()

    assert exc_info.value.error.code == types.INVALID_PARAMS

    # logfire also exports a `pending_span` marker under each span's name when it starts.
    spans = {
        span.name: span
        for span in capfire.exporter.exported_spans
        if (span.attributes or {}).get("logfire.span_type") != "pending_span"
    }
    succeeded = spans["MCP send tools/list"]
    failed = spans["MCP send prompts/list"]

    assert succeeded.status.status_code == StatusCode.UNSET
    assert failed.status.status_code == StatusCode.ERROR
    assert failed.status.description == message
    assert failed.attributes is not None
    assert failed.attributes["error.type"] == str(types.INVALID_PARAMS)
    assert failed.attributes["rpc.response.status_code"] == str(types.INVALID_PARAMS)


async def test_client_and_server_spans_agree_on_tool_error(capfire: CaptureLogfire):
    """When tools/call returns a CallToolResult with isError=true, both the client and server spans
    must record status ERROR and error.type='tool_error', while a successful tools/call leaves both
    spans UNSET (#3810).
    """
    server = MCPServer("test")

    @server.tool()
    def ok_tool() -> str:
        return "ok"

    @server.tool()
    def failing_tool() -> types.CallToolResult:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="tool failure")],
            is_error=True,
        )

    @server.tool()
    def protocol_error_tool() -> str:
        raise MCPError(types.INTERNAL_ERROR, "upstream failure")

    async with Client(server, mode="legacy") as client:
        ok_res = await client.call_tool("ok_tool", {})
        err_res = await client.call_tool("failing_tool", {})
        with pytest.raises(MCPError):
            await client.call_tool("protocol_error_tool", {})

    assert not ok_res.is_error
    assert err_res.is_error

    spans = {
        span.name: span
        for span in capfire.exporter.exported_spans
        if (span.attributes or {}).get("logfire.span_type") != "pending_span"
    }

    # 1. Successful tool call leaves both client and server spans UNSET
    assert spans["MCP send tools/call ok_tool"].status.status_code == StatusCode.UNSET
    assert "error.type" not in (spans["MCP send tools/call ok_tool"].attributes or {})
    assert spans["tools/call ok_tool"].status.status_code == StatusCode.UNSET

    # 2. Tool error (isError=true) sets ERROR and error.type="tool_error" on both spans
    client_tool_err = spans["MCP send tools/call failing_tool"]
    server_tool_err = spans["tools/call failing_tool"]
    assert client_tool_err.status.status_code == StatusCode.ERROR
    assert server_tool_err.status.status_code == StatusCode.ERROR
    assert (client_tool_err.attributes or {}).get("error.type") == "tool_error"
    assert (server_tool_err.attributes or {}).get("error.type") == "tool_error"

    # 3. Protocol error sets ERROR and matching error.type code on both spans
    client_proto_err = spans["MCP send tools/call protocol_error_tool"]
    server_proto_err = spans["tools/call protocol_error_tool"]
    assert client_proto_err.status.status_code == StatusCode.ERROR
    assert server_proto_err.status.status_code == StatusCode.ERROR
    assert (client_proto_err.attributes or {}).get("error.type") == str(types.INTERNAL_ERROR)
    assert (server_proto_err.attributes or {}).get("error.type") == str(types.INTERNAL_ERROR)

