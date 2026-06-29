"""Legacy-wire protection: a 2025-era streamable-HTTP exchange stays free of 2026 vocabulary.

Records the round trip at both seams (HTTP headers, JSON-RPC frames) and scans it with
`assert_no_modern_vocabulary`; the forbidden tokens live in `tests.interaction._modern_vocab`.
"""

import httpx
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext
from mcp.shared.message import SessionMessage
from tests.interaction._connect import BASE_URL, mounted_app
from tests.interaction._helpers import RecordingTransport
from tests.interaction._modern_vocab import RecordedExchange, assert_no_modern_vocabulary
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


def _server() -> Server:
    """One echo tool so the recorded exchange covers tools/list and tools/call."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="echo", description="Echo text.", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "echo"
        assert params.arguments is not None
        return CallToolResult(content=[TextContent(text=str(params.arguments["text"]))])

    return Server("legacy", on_list_tools=list_tools, on_call_tool=call_tool)


@requirement("hosting:http:legacy-no-modern-vocabulary")
async def test_legacy_streamable_http_exchange_carries_no_modern_protocol_vocabulary() -> None:
    """SDK-defined under the draft versioning rules: today's wire must stay free of 2026 vocabulary.

    The client API exposes neither seam, so the check is necessarily wire-level.
    """
    recorded = RecordedExchange(requests=[], responses=[], frames=[])

    async def on_request(request: httpx.Request) -> None:
        recorded.requests.append(request)

    async def on_response(response: httpx.Response) -> None:
        recorded.responses.append(response)

    async with mounted_app(_server(), on_request=on_request, on_response=on_response) as (http, _):
        recording = RecordingTransport(streamable_http_client(f"{BASE_URL}/mcp", http_client=http))
        async with Client(recording, mode="legacy") as client:
            result = await client.call_tool("echo", {"text": "legacy"})

    assert result == snapshot(CallToolResult(content=[TextContent(text="legacy")]))

    recorded.frames.extend(m.message for m in recording.sent)
    recorded.frames.extend(m.message for m in recording.received if isinstance(m, SessionMessage))

    # Handshake, implicit tools/list (output-schema cache), tools/call, standalone GET stream, and
    # closing DELETE; asserting non-empty so the vocabulary scan cannot pass on nothing recorded.
    assert {r.method for r in recorded.requests} == snapshot({"POST", "GET", "DELETE"})
    assert len(recorded.responses) == len(recorded.requests)
    assert len(recorded.frames) >= 6

    assert_no_modern_vocabulary(recorded)
