"""Streamable HTTP at protocol version 2026-07-28: the single-exchange stateless serving entry.

These tests speak HTTP directly to the server's mounted ASGI app via the in-process bridge,
asserting the wire contract for a 2026-07-28 POST -- one self-contained request, no initialize
handshake, no ``Mcp-Session-Id``, JSON response body -- and that 2025-era traffic on the same
endpoint is byte-unchanged. The SDK client never exposes the response headers or the raw
result-envelope shape, so every assertion here is necessarily wire-level.
"""

import json
from collections.abc import Callable
from typing import Any

import anyio
import httpx
import pytest
from inline_snapshot import snapshot

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    CallToolRequestParams,
    CallToolResult,
    Implementation,
    JSONRPCError,
    JSONRPCResponse,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)
from tests.interaction._connect import BASE_URL, base_headers, initialize_body, initialize_via_http, mounted_app
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


def _server(*, on_meta: Callable[[dict[str, Any]], None] | None = None) -> Server:
    """A low-level server with one ``add`` tool for the raw-httpx tests below."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        tool = Tool(name="add", input_schema={"type": "object"})
        return ListToolsResult(tools=[tool], ttl_ms=0, cache_scope="public")

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "add"
        assert params.arguments is not None
        if on_meta is not None:
            assert ctx.meta is not None
            on_meta(dict(ctx.meta))
        return CallToolResult(content=[TextContent(text=str(params.arguments["a"] + params.arguments["b"]))])

    return Server("modern", on_list_tools=list_tools, on_call_tool=call_tool)


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


@requirement("hosting:http:modern:legacy-fallthrough")
async def test_non_modern_version_header_falls_through_to_legacy_transport_unchanged() -> None:
    """The 2026-07-28 routing branch fires only on its exact header; everything else reaches legacy.

    SDK-defined under the draft versioning rules: the modern entry must not change any 2025-era
    byte. A 2025-era initialize on the same endpoint still completes (legacy serves it), and an
    unrecognised ``MCP-Protocol-Version`` still falls through to the legacy gate and produces the
    ``Unsupported protocol version`` literal that peer SDKs substring-sniff. Asserted at the wire
    because the literal is only observable in the raw response body.
    """
    async with mounted_app(_server()) as (http, _):
        # 2025-era initialize through the same endpoint: the modern branch must not intercept it.
        session_id = await initialize_via_http(http)
        unrecognised = await http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            headers=base_headers(session_id=session_id) | {"mcp-protocol-version": "9999-01-01"},
        )

    assert unrecognised.status_code == 400
    assert "Unsupported protocol version" in unrecognised.text


@requirement("hosting:http:modern:handler-exception-internal-error")
async def test_modern_handler_exception_maps_to_internal_error_without_leaking_the_message() -> None:
    """A handler exception on the 2026-07-28 path returns -32603 with a generic message.

    Spec-mandated for the code: -32603 is the JSON-RPC Internal error code. SDK-defined for the
    message: the 2026-07-28 entry deliberately does not echo ``str(exc)`` (the legacy dispatcher's
    code-0 leak is the recorded divergence on ``protocol:error:internal-error``). Asserted at the
    wire because the SDK client surfaces only the error object, not the HTTP status it travelled on.
    """

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "boom"
        raise RuntimeError("kaboom")

    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "boom", "arguments": {}, "_meta": _meta_envelope()},
    }
    async with mounted_app(Server("modern", on_call_tool=call_tool)) as (http, _):
        response = await http.post("/mcp", json=body, headers=_modern_headers(method="tools/call", name="boom"))

    assert response.status_code == 200
    error = JSONRPCError.model_validate(response.json()).error
    assert error.code == INTERNAL_ERROR
    assert "kaboom" not in error.message


@requirement("hosting:http:modern:tools-call-stateless")
@requirement("lifecycle:stateless:request-envelope")
@requirement("lifecycle:stateless:caller-meta-preserved")
@requirement("client-transport:http:body-derived-headers")
async def test_pinned_client_stateless_tools_call_round_trips_against_the_modern_entry() -> None:
    """First end-to-end exercise of the 2026-07-28 stateless request style: SDK client to SDK server.

    Spec-mandated under the draft stateless transport: the pinned ``ClientSession`` and the
    single-exchange serving entry compose so that ``call_tool`` returns ``resultType: complete``
    with no ``initialize`` ever sent, no ``Mcp-Session-Id`` on any request or response, and every
    POST carrying the body-derived ``MCP-Protocol-Version`` / ``Mcp-Method`` / ``Mcp-Name`` headers
    plus the three-key ``io.modelcontextprotocol/*`` ``_meta`` envelope. The caller passes a
    ``custom-key`` under ``meta=`` and the server handler captures the incoming ``ctx.meta``,
    proving the envelope merge is additive: the caller's key sits alongside the three envelope keys
    on the wire and inside the handler. Asserted at the wire via the ``mounted_app`` httpx event
    hooks because none of the headers, the envelope, or the handshake-absence is observable through
    the public client API. The recorded log shows two POSTs: the ``tools/call`` itself and the
    client's implicit ``tools/list`` output-schema fetch (see ``client:output-schema:auto-list``),
    both of which must satisfy the stateless contract.
    """
    observed_metas: list[dict[str, Any]] = []
    server = _server(on_meta=observed_metas.append)

    requests: list[httpx.Request] = []
    responses: list[httpx.Response] = []

    async def on_request(request: httpx.Request) -> None:
        requests.append(request)

    async def on_response(response: httpx.Response) -> None:
        responses.append(response)

    client_info = Implementation(name="e2e-client", version="1.0.0")
    with anyio.fail_after(5):
        async with (
            mounted_app(server, on_request=on_request, on_response=on_response) as (http, _),
            streamable_http_client(f"{BASE_URL}/mcp", http_client=http, protocol_version=MODERN_VERSION) as (
                read,
                write,
            ),
            ClientSession(read, write, client_info=client_info, protocol_version=MODERN_VERSION) as session,
        ):
            result = await session.call_tool(
                "add",
                {"a": 2, "b": 3},
                meta={"custom-key": "x", "io.modelcontextprotocol/protocolVersion": "evil"},
            )

    assert result.model_dump(by_alias=True, mode="json", exclude_none=True) == snapshot(
        {"content": [{"type": "text", "text": "5"}], "isError": False, "resultType": "complete"}
    )

    # Exactly the tools/call POST and the implicit tools/list POST -- no initialize, no
    # notifications/initialized, no standalone GET stream, no closing DELETE.
    bodies = [json.loads(r.content) for r in requests]
    assert [(r.method, body["method"]) for r, body in zip(requests, bodies, strict=True)] == snapshot(
        [("POST", "tools/call"), ("POST", "tools/list")]
    )
    assert all("initialize" not in body["method"] for body in bodies)

    # The tools/call POST carries the body-derived headers, and its _meta envelope overwrites the
    # caller's colliding io.modelcontextprotocol/* key while preserving the non-colliding caller key.
    call = requests[0]
    assert {k: v for k, v in call.headers.items() if k.startswith("mcp-")} == snapshot(
        {"mcp-protocol-version": "2026-07-28", "mcp-method": "tools/call", "mcp-name": "add"}
    )
    assert bodies[0]["params"]["_meta"] == snapshot(
        {
            "custom-key": "x",
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientInfo": {"name": "e2e-client", "version": "1.0.0"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    )
    # The implicit tools/list carries the envelope but no caller meta: proves the envelope is
    # stamped on every request, not just on requests where the caller passed meta=.
    assert bodies[1]["params"]["_meta"] == snapshot(
        {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientInfo": {"name": "e2e-client", "version": "1.0.0"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    )

    # The server handler observed the same merged _meta on ctx.meta.
    assert observed_metas == [bodies[0]["params"]["_meta"]]

    # No session id on any request or response: the exchange is sessionless end to end.
    assert len(responses) == len(requests)
    assert all("mcp-session-id" not in r.headers for r in requests)
    assert all("mcp-session-id" not in r.headers for r in responses)
