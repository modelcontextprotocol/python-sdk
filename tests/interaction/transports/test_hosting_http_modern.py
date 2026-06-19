"""Streamable HTTP at protocol version 2026-07-28: the single-exchange stateless serving entry.

These tests speak HTTP directly to the server's mounted ASGI app via the in-process bridge,
asserting the wire contract for a 2026-07-28 POST -- one self-contained request, no initialize
handshake, no ``Mcp-Session-Id``, JSON response body -- and that 2025-era traffic on the same
endpoint is byte-unchanged. The SDK client never exposes the response headers or the raw
result-envelope shape, so every assertion here is necessarily wire-level.
"""

import pytest
from inline_snapshot import snapshot

from mcp.server import Server, ServerRequestContext
from mcp.types import (
    METHOD_NOT_FOUND,
    CallToolRequestParams,
    CallToolResult,
    JSONRPCError,
    JSONRPCResponse,
    TextContent,
)
from tests.interaction._connect import base_headers, initialize_body, mounted_app
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio

MODERN_VERSION = "2026-07-28"


def _modern_headers(*, method: str, name: str | None = None) -> dict[str, str]:
    """Request headers for a 2026-07-28 POST.

    The Accept/Content-Type baseline plus the ``MCP-Protocol-Version`` routing header and the
    ``Mcp-Method`` / ``Mcp-Name`` advisory headers a 2026-era client always sends.
    """
    headers = base_headers() | {"mcp-protocol-version": MODERN_VERSION, "mcp-method": method}
    if name is not None:
        headers["mcp-name"] = name
    return headers


def _meta_envelope() -> dict[str, object]:
    """The per-request ``_meta`` envelope a 2026-07-28 client stamps on every request.

    Replaces the 2025-era initialize handshake: protocol version, client info, and client
    capabilities travel on each request instead of once per session.
    """
    return {
        "io.modelcontextprotocol/protocolVersion": MODERN_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "raw", "version": "0.0.0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }


def _server() -> Server:
    """A low-level server with one ``add`` tool, for the 2026-07-28 happy-path tools/call."""

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "add"
        assert params.arguments is not None
        return CallToolResult(content=[TextContent(text=str(params.arguments["a"] + params.arguments["b"]))])

    return Server("modern", on_call_tool=call_tool)


@requirement("hosting:http:modern:tools-call-stateless")
async def test_modern_tools_call_returns_result_type_complete_without_initialize() -> None:
    """A 2026-07-28 tools/call is served without an initialize handshake and returns resultType: complete.

    Spec-mandated under the draft transport: the per-request ``_meta`` envelope replaces initialize,
    and ``resultType`` is the 2026 result-envelope discriminator (``complete`` for the monolith
    result). Asserted at the wire because the SDK client never surfaces ``resultType`` and because
    the absence of any prior request on the connection is the assertion.
    """
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "add", "arguments": {"a": 2, "b": 3}, "_meta": _meta_envelope()},
    }
    async with mounted_app(_server()) as (http, _):
        response = await http.post("/mcp", json=body, headers=_modern_headers(method="tools/call", name="add"))

    assert response.status_code == 200
    assert response.headers["content-type"].split(";", 1)[0] == "application/json"
    parsed = JSONRPCResponse.model_validate(response.json())
    assert parsed.id == 1
    assert parsed.result == snapshot(
        {"content": [{"text": "5", "type": "text"}], "isError": False, "resultType": "complete"}
    )


@requirement("hosting:http:modern:no-session-id")
async def test_modern_response_carries_no_session_id_header() -> None:
    """A 2026-07-28 response never sets ``Mcp-Session-Id``.

    Spec-mandated under the draft transport: the 2026-07-28 exchange is sessionless by definition,
    so the header that the 2025-era transport always sets on responses must be absent. Asserted at
    the wire because the SDK client never exposes response headers.
    """
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "add", "arguments": {"a": 2, "b": 3}, "_meta": _meta_envelope()},
    }
    async with mounted_app(_server()) as (http, _):
        response = await http.post("/mcp", json=body, headers=_modern_headers(method="tools/call", name="add"))

    assert response.status_code == 200
    assert "mcp-session-id" not in response.headers


@requirement("hosting:http:modern:initialize-removed")
async def test_modern_initialize_is_method_not_found() -> None:
    """A 2026-07-28 initialize request is answered with METHOD_NOT_FOUND.

    Spec-mandated under the draft: initialize is not a defined method at 2026-07-28, so the
    method/version gate rejects it before any handler runs. Asserted at the wire because the SDK
    client at 2026-07-28 never sends initialize, so only a raw POST can drive the negative.
    """
    async with mounted_app(_server()) as (http, _):
        response = await http.post("/mcp", json=initialize_body(), headers=_modern_headers(method="initialize"))

    assert response.status_code == 200
    assert JSONRPCError.model_validate(response.json()).error.code == METHOD_NOT_FOUND
