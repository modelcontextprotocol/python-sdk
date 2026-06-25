"""Legacy-wire protection: a 2025-era streamable-HTTP exchange stays free of 2026 vocabulary.

Records a full SDK client -> SDK server round trip at both seams (HTTP request/response headers
via httpx event hooks; JSON-RPC frames in both directions via the recording transport) and runs
the result through :func:`tests.interaction._modern_vocab.assert_no_modern_vocabulary`. The test
pins today's wire so any future 2026-07-28 work that leaks new fields, `_meta` keys, or headers
onto a connection negotiated at the current protocol version fails here.
"""

import httpx
import pytest
from inline_snapshot import snapshot

from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext
from mcp.shared.message import SessionMessage
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)
from tests.interaction._connect import BASE_URL, mounted_app
from tests.interaction._helpers import RecordingTransport
from tests.interaction._modern_vocab import RecordedExchange, assert_no_modern_vocabulary
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


def _server() -> Server:
    """A low-level server with one echo tool, so the recorded exchange covers tools/list and tools/call."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="echo", description="Echo text.", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "echo"
        assert params.arguments is not None
        return CallToolResult(content=[TextContent(text=str(params.arguments["text"]))])

    return Server("legacy", on_list_tools=list_tools, on_call_tool=call_tool)


@requirement("hosting:http:legacy-no-modern-vocabulary")
async def test_legacy_streamable_http_exchange_carries_no_modern_protocol_vocabulary() -> None:
    """A 2025-era client/server round trip emits none of the 2026-07-28 wire vocabulary.

    SDK-defined under the draft versioning rules: pins the current wire so future 2026 work cannot
    leak `resultType` / `ttlMs` / `cacheScope`, `io.modelcontextprotocol/*` `_meta` keys, the
    `2026-07-28` literal, or `Mcp-Method` / `Mcp-Name` / `Mcp-Param-*` headers onto a connection
    negotiated at the current protocol version. Recorded at the HTTP seam (every request and
    response header) and the transport seam (every JSON-RPC frame in either direction); the SDK
    client never exposes either, so the assertion is necessarily wire-level.
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

    # The handshake, the implicit tools/list (output-schema cache), tools/call, the standalone GET
    # stream, and the closing DELETE all crossed the HTTP seam; the transport seam saw a JSON-RPC
    # frame for each direction of each. Asserting non-empty so the vocabulary scan cannot pass on
    # nothing recorded.
    assert {r.method for r in recorded.requests} == snapshot({"POST", "GET", "DELETE"})
    assert len(recorded.responses) == len(recorded.requests)
    assert len(recorded.frames) >= 6

    assert_no_modern_vocabulary(recorded)
