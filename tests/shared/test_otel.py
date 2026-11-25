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
