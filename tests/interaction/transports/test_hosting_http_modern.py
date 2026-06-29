"""Streamable HTTP at protocol version 2026-07-28: the single-exchange stateless serving entry.

These tests speak HTTP directly to the server's mounted ASGI app via the in-process bridge,
asserting the wire contract for a 2026-07-28 POST -- one self-contained request, no initialize
handshake, no `Mcp-Session-Id`, JSON response body -- and that 2025-era traffic on the same
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
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    CallToolRequestParams,
    CallToolResult,
    DiscoverResult,
    EmptyResult,
    Implementation,
    JSONRPCError,
    JSONRPCResponse,
    ListToolsResult,
    PaginatedRequestParams,
    RequestParams,
    ServerCapabilities,
    TextContent,
    Tool,
)
from mcp_types.version import LATEST_MODERN_VERSION

from mcp import MCPError
from mcp.client.client import Client
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext
from tests.interaction._connect import BASE_URL, base_headers, initialize_via_http, mounted_app
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


def _modern_headers(*, method: str, name: str | None = None) -> dict[str, str]:
    """Request headers for a 2026-07-28 POST: routing and advisory headers atop the Accept/Content-Type baseline."""
    headers = base_headers() | {"mcp-protocol-version": LATEST_MODERN_VERSION, "mcp-method": method}
    if name is not None:
        headers["mcp-name"] = name
    return headers


def _meta_envelope() -> dict[str, object]:
    """The per-request `_meta` envelope that replaces the 2025-era initialize handshake."""
    return {
        "io.modelcontextprotocol/protocolVersion": LATEST_MODERN_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "raw", "version": "0.0.0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }


def _server(*, on_meta: Callable[[dict[str, Any]], None] | None = None) -> Server:
    """A low-level server with one `add` tool for the raw-httpx tests below."""

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
    """`resultType` is the 2026 result-envelope discriminator; `complete` marks the monolith result."""
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
    """The 2026-07-28 exchange is sessionless, so the header the 2025-era transport always sets must be absent."""
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
    """The valid `_meta` envelope lets the request past the classifier to the kernel's method/version gate.

    Without it the rejection would be INVALID_PARAMS at rung 1, never METHOD_NOT_FOUND.
    """
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"_meta": _meta_envelope()}}
    async with mounted_app(_server()) as (http, _):
        response = await http.post("/mcp", json=body, headers=_modern_headers(method="initialize"))

    assert response.status_code == 404
    assert JSONRPCError.model_validate(response.json()).error.code == METHOD_NOT_FOUND


@requirement("hosting:http:modern:legacy-fallthrough")
async def test_legacy_version_header_falls_through_and_unrecognised_header_routes_to_modern() -> None:
    """Only known initialize-handshake versions reach the legacy transport.

    Any other `MCP-Protocol-Version` routes to the modern entry, the single owner of
    unknown-version rejection (the envelope-less request fails the ladder's first rung as
    INVALID_PARAMS).
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
    assert JSONRPCError.model_validate_json(unrecognised.text).error.code == INVALID_PARAMS


@requirement("hosting:http:modern:handler-exception-internal-error")
async def test_modern_handler_exception_maps_to_internal_error_without_leaking_the_message() -> None:
    """The 2026-07-28 entry deliberately does not echo `str(exc)`.

    The legacy dispatcher's code-0 leak is the recorded divergence on `protocol:error:internal-error`.
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


@requirement("hosting:http:modern:discover-response-shape")
async def test_modern_server_discover_returns_capabilities_and_supported_versions() -> None:
    """`server/discover` replaces the initialize-response advertisement.

    `supportedVersions` is the field a client picks its per-request envelope version from.
    """
    body = {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": _meta_envelope()}}
    async with mounted_app(_server()) as (http, _):
        response = await http.post("/mcp", json=body, headers=_modern_headers(method="server/discover"))

    assert response.status_code == 200
    result = JSONRPCResponse.model_validate(response.json()).result
    assert result["supportedVersions"] == snapshot(["2026-07-28"])
    assert result["serverInfo"]["name"] == "modern"
    assert "capabilities" in result


@requirement("hosting:http:modern:removed-method-status-404")
async def test_modern_removed_method_is_method_not_found_at_http_404() -> None:
    """The error code is spec-mandated; the HTTP 404 is SDK-defined.

    Kernel-origin METHOD_NOT_FOUND maps through the same error-code-to-status table as
    classifier-origin errors.
    """
    body = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"_meta": _meta_envelope()}}
    async with mounted_app(_server()) as (http, _):
        response = await http.post("/mcp", json=body, headers=_modern_headers(method="ping"))

    assert response.status_code == 404
    assert JSONRPCError.model_validate(response.json()).error.code == METHOD_NOT_FOUND


@requirement("hosting:http:modern:envelope-missing-key-status-400")
async def test_modern_envelope_missing_required_meta_key_is_invalid_params_at_http_400() -> None:
    """A missing reserved envelope key fails the classifier's first rung, before any kernel dispatch."""
    incomplete = _meta_envelope()
    del incomplete[CLIENT_CAPABILITIES_META_KEY]
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": incomplete}}
    async with mounted_app(_server()) as (http, _):
        response = await http.post("/mcp", json=body, headers=_modern_headers(method="tools/list"))

    assert response.status_code == 400
    assert JSONRPCError.model_validate(response.json()).error.code == INVALID_PARAMS


@requirement("hosting:http:modern:handler-error-status-via-table")
async def test_modern_handler_raised_mcperror_maps_to_status_via_error_code_table() -> None:
    """Handler-origin error codes map through the same error-code-to-status table as classifier-origin ones.

    `error.data` is preserved. Registered via the low-level `add_request_handler` so the
    high-level tool wrapper's error-swallowing is not on the path.
    """

    async def cap_check(ctx: ServerRequestContext, params: RequestParams) -> EmptyResult:
        raise MCPError(
            code=MISSING_REQUIRED_CLIENT_CAPABILITY,
            message="sampling required",
            data={"requiredCapabilities": ["sampling"]},
        )

    server = _server()
    server.add_request_handler("test/cap-check", RequestParams, cap_check)
    body = {"jsonrpc": "2.0", "id": 1, "method": "test/cap-check", "params": {"_meta": _meta_envelope()}}
    async with mounted_app(server) as (http, _):
        response = await http.post("/mcp", json=body, headers=_modern_headers(method="test/cap-check"))

    assert response.status_code == 400
    error = JSONRPCError.model_validate(response.json()).error
    assert error.code == MISSING_REQUIRED_CLIENT_CAPABILITY
    assert error.data == {"requiredCapabilities": ["sampling"]}


@requirement("hosting:http:modern:tools-call-stateless")
@requirement("lifecycle:stateless:request-envelope")
@requirement("lifecycle:stateless:caller-meta-preserved")
@requirement("client-transport:http:body-derived-headers")
async def test_pinned_client_stateless_tools_call_round_trips_against_the_modern_entry() -> None:
    """End-to-end 2026-07-28 stateless round trip: a pinned `ClientSession` against the modern entry.

    Observed via the `mounted_app` httpx event hooks. Two POSTs are expected -- the `tools/call`
    and the client's implicit `tools/list` output-schema fetch (see `client:output-schema:auto-list`)
    -- and both must satisfy the stateless contract.
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
            streamable_http_client(f"{BASE_URL}/mcp", http_client=http) as (read, write),
            ClientSession(read, write, client_info=client_info) as session,
        ):
            session.adopt(
                DiscoverResult(
                    supported_versions=[LATEST_MODERN_VERSION],
                    capabilities=ServerCapabilities(),
                    server_info=Implementation(name="srv", version="0"),
                )
            )
            result = await session.call_tool(
                "add",
                {"a": 2, "b": 3},
                meta={"custom-key": "x", "io.modelcontextprotocol/protocolVersion": "evil"},
            )

    assert result.model_dump(by_alias=True, mode="json", exclude_none=True) == snapshot(
        {"content": [{"type": "text", "text": "5"}], "isError": False, "resultType": "complete"}
    )

    # Only the tools/call and implicit tools/list POSTs: no initialize, no GET stream, no closing DELETE.
    bodies = [json.loads(r.content) for r in requests]
    assert [(r.method, body["method"]) for r, body in zip(requests, bodies, strict=True)] == snapshot(
        [("POST", "tools/call"), ("POST", "tools/list")]
    )
    assert all("initialize" not in body["method"] for body in bodies)

    # The envelope overwrites the caller's colliding io.modelcontextprotocol/* key and preserves `custom-key`.
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
    # The implicit tools/list carries the envelope with no caller meta: stamped on every request, not just meta= calls.
    assert bodies[1]["params"]["_meta"] == snapshot(
        {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientInfo": {"name": "e2e-client", "version": "1.0.0"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    )

    assert observed_metas == [bodies[0]["params"]["_meta"]]

    assert len(responses) == len(requests)
    assert all("mcp-session-id" not in r.headers for r in requests)
    assert all("mcp-session-id" not in r.headers for r in responses)


_CUSTOM_HEADER_TOOL = Tool(
    name="run",
    input_schema={
        "type": "object",
        "properties": {
            "region": {"type": "string", "x-mcp-header": "Region"},
            "priority": {"type": "integer", "x-mcp-header": "Priority"},
            "verbose": {"type": "boolean", "x-mcp-header": "Verbose"},
            "note": {"type": "string", "x-mcp-header": "Note"},
            "query": {"type": "string"},
        },
        "required": ["region"],
    },
)


def _custom_header_server() -> Server:
    """A server with one tool whose schema annotates four args with `x-mcp-header` and leaves `query` plain."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[_CUSTOM_HEADER_TOOL], ttl_ms=0, cache_scope="public")

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        return CallToolResult(content=[TextContent(text="ok")])

    return Server("custom-headers", on_list_tools=list_tools, on_call_tool=call_tool)


@requirement("client-transport:http:custom-param-headers")
async def test_modern_client_mirrors_x_mcp_header_args_into_mcp_param_headers() -> None:
    """`list_tools` caches the tool's annotations; the client then mirrors annotated arguments into headers.

    Each value is rendered per the spec's Value Encoding rules -- string verbatim, integer as
    decimal, boolean lowercase, non-ASCII base64-sentinel-wrapped -- while unannotated arguments
    stay out of the headers.
    """
    requests: list[httpx.Request] = []

    async def on_request(request: httpx.Request) -> None:
        requests.append(request)

    discover = DiscoverResult(
        supported_versions=[LATEST_MODERN_VERSION],
        capabilities=ServerCapabilities(),
        server_info=Implementation(name="srv", version="0"),
    )
    with anyio.fail_after(5):
        async with (
            mounted_app(_custom_header_server(), on_request=on_request) as (http, _),
            Client(
                streamable_http_client(f"{BASE_URL}/mcp", http_client=http),
                mode=LATEST_MODERN_VERSION,
                prior_discover=discover,
            ) as client,
        ):
            await client.list_tools()
            await client.call_tool("run", {"region": "us-west1", "priority": 42, "verbose": False, "note": "héllo"})

    call = next(r for r in requests if json.loads(r.content)["method"] == "tools/call")
    assert {k: v for k, v in call.headers.items() if k.startswith("mcp-param-")} == snapshot(
        {
            "mcp-param-region": "us-west1",
            "mcp-param-priority": "42",
            "mcp-param-verbose": "false",
            "mcp-param-note": "=?base64?aMOpbGxv?=",
        }
    )
    # Mirroring is additive: the arguments are unchanged in the body.
    assert json.loads(call.content)["params"]["arguments"] == snapshot(
        {"region": "us-west1", "priority": 42, "verbose": False, "note": "héllo"}
    )


@requirement("client-transport:http:custom-param-headers")
async def test_modern_client_emits_no_param_headers_for_an_unlisted_tool() -> None:
    """The spec lets a client lacking the tool's `inputSchema` send the call without custom headers.

    The first `tools/call` POST is captured before the implicit output-schema `list_tools` runs.
    """
    requests: list[httpx.Request] = []

    async def on_request(request: httpx.Request) -> None:
        if json.loads(request.content)["method"] == "tools/call":
            requests.append(request)

    discover = DiscoverResult(
        supported_versions=[LATEST_MODERN_VERSION],
        capabilities=ServerCapabilities(),
        server_info=Implementation(name="srv", version="0"),
    )
    with anyio.fail_after(5):
        async with (
            mounted_app(_custom_header_server(), on_request=on_request) as (http, _),
            Client(
                streamable_http_client(f"{BASE_URL}/mcp", http_client=http),
                mode=LATEST_MODERN_VERSION,
                prior_discover=discover,
            ) as client,
        ):
            await client.call_tool("run", {"region": "us-west1"})

    assert not any(k.startswith("mcp-param-") for k in requests[0].headers)


@requirement("client-transport:http:custom-param-headers")
async def test_modern_client_stops_mirroring_after_a_re_list_drops_the_tool() -> None:
    """The re-list returns the tool with an invalid annotation; the client evicts the cached header map.

    A later `tools/call` by name therefore mirrors nothing.
    """
    schema = {"type": "object", "properties": {"a": {"type": "string", "x-mcp-header": "Region"}}}
    bad_schema = {"type": "object", "properties": {"a": {"type": "string", "x-mcp-header": "bad name"}}}
    valid = Tool(name="run", input_schema=schema)
    invalid = Tool(name="run", input_schema=bad_schema)
    listings = iter([valid, invalid])

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[next(listings)], ttl_ms=0, cache_scope="public")

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        return CallToolResult(content=[TextContent(text="ok")])

    server = Server("evict", on_list_tools=list_tools, on_call_tool=call_tool)

    tool_calls: list[httpx.Request] = []

    async def on_request(request: httpx.Request) -> None:
        if json.loads(request.content)["method"] == "tools/call":
            tool_calls.append(request)

    discover = DiscoverResult(
        supported_versions=[LATEST_MODERN_VERSION],
        capabilities=ServerCapabilities(),
        server_info=Implementation(name="srv", version="0"),
    )
    with anyio.fail_after(5):
        async with (
            mounted_app(server, on_request=on_request) as (http, _),
            Client(
                streamable_http_client(f"{BASE_URL}/mcp", http_client=http),
                mode=LATEST_MODERN_VERSION,
                prior_discover=discover,
            ) as client,
        ):
            assert [t.name for t in (await client.list_tools()).tools] == ["run"]
            await client.call_tool("run", {"a": "x"})

            assert [t.name for t in (await client.list_tools()).tools] == []
            await client.call_tool("run", {"a": "x"})

    before, after = tool_calls
    assert before.headers.get("mcp-param-region") == "x"
    assert not any(k.startswith("mcp-param-") for k in after.headers)
