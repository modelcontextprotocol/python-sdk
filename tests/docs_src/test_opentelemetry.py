"""`docs/advanced/opentelemetry.md`: every claim the page makes, proved against the real SDK."""

import pytest
from logfire.testing import CaptureLogfire

from docs_src.opentelemetry import tutorial001
from mcp import Client

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_a_plain_server_is_traced_with_no_extra_code(capfire: CaptureLogfire) -> None:
    """tutorial001: calling a tool emits a `tools/call` SERVER span, though the example adds no middleware."""
    async with Client(tutorial001.mcp) as client:
        await client.call_tool("search_books", {"query": "dune"})

    spans = {s["name"]: s for s in capfire.exporter.exported_spans_as_dict()}
    assert "tools/call search_books" in spans

    attributes = spans["tools/call search_books"]["attributes"]
    assert attributes["mcp.method.name"] == "tools/call"
    assert attributes["gen_ai.operation.name"] == "execute_tool"
    assert attributes["gen_ai.tool.name"] == "search_books"


async def test_client_and_server_share_one_trace(capfire: CaptureLogfire) -> None:
    """When both sides run the SDK, the client and server spans land in one trace (SEP-414)."""
    async with Client(tutorial001.mcp, mode="legacy") as client:
        await client.call_tool("search_books", {"query": "dune"})

    spans = {s["name"]: s for s in capfire.exporter.exported_spans_as_dict()}
    client_span = spans["MCP send tools/call search_books"]
    server_span = spans["tools/call search_books"]
    assert server_span["context"]["trace_id"] == client_span["context"]["trace_id"]
