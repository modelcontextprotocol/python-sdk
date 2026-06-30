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
import httpx2
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
    """Request headers for a 2026-07-28 POST.

    The Accept/Content-Type baseline plus the ``MCP-Protocol-Version`` routing header and the
    ``Mcp-Method`` / ``Mcp-Name`` advisory headers a 2026-era client always sends.
    """
    headers = base_headers() | {"mcp-protocol-version": LATEST_MODERN_VERSION, "mcp-method": method}
    if name is not None:
        headers["mcp-name"] = name
    return headers


def _meta_envelope() -> dict[str, object]:
    """The per-request ``_meta`` envelope a 2026-07-28 client stamps on every request.

    Replaces the 2025-era initialize handshake: protocol version, client info, and client
    capabilities travel on each request instead of once per session.
    """
    return {
        "io.modelcontextprotocol/protocolVersion": LATEST_MODERN_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "raw", "version": "0.0.0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }


def _server(*, on_meta: Callable[[dict[str, Any]], None] | None = None) -> Server:
    """A low-level server with one ``add`` tool for the raw-httpx2 tests below."""

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
    """A 2026-07-28 initialize request that carries a valid envelope is answered METHOD_NOT_FOUND at HTTP 404.

    Spec-mandated under the draft: initialize is not a defined method at 2026-07-28, so the kernel's
    method/version gate rejects it before any handler runs. The body must carry the per-request
    ``_meta`` envelope so the classifier ladder admits it as far as kernel dispatch -- without the
    envelope the request is INVALID_PARAMS at rung 1, never METHOD_NOT_FOUND. Asserted at the wire
    because the SDK client at 2026-07-28 never sends initialize, so only a raw POST can drive the
    negative.
    """
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"_meta": _meta_envelope()}}
    async with mounted_app(_server()) as (http, _):
        response = await http.post("/mcp", json=body, headers=_modern_headers(method="initialize"))

    assert response.status_code == 404
    assert JSONRPCError.model_validate(response.json()).error.code == METHOD_NOT_FOUND


@requirement("hosting:http:modern:legacy-fallthrough")
async def test_legacy_version_header_falls_through_and_unrecognised_header_routes_to_modern() -> None:
    """SDK-defined under the draft versioning rules: only the known initialize-handshake protocol
    versions reach the legacy transport, so a 2025-era ``initialize`` on the same endpoint still
    completes unchanged. Any other ``MCP-Protocol-Version`` value routes to the modern entry,
    where the validation ladder rejects it (a request without the per-request envelope fails the
    first rung). The modern entry is therefore the single owner of unknown-version rejection.
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


@requirement("hosting:http:modern:discover-response-shape")
async def test_modern_server_discover_returns_capabilities_and_supported_versions() -> None:
    """A 2026-07-28 server/discover POST returns capabilities, serverInfo, and supportedVersions.

    Spec-mandated under the draft: server/discover is the 2026 advertisement method that replaces
    the initialize-response payload, and ``supportedVersions`` is the field a client picks its
    per-request envelope version from. Asserted at the wire because the SDK client never exposes
    the raw result body.
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
    """A 2026-07-28 ping (removed at 2026) is answered METHOD_NOT_FOUND and the HTTP status is 404.

    Spec-mandated for the error code: ping is not a defined method at 2026-07-28 so the kernel's
    method/version gate rejects it. SDK-defined for the HTTP status: kernel-origin METHOD_NOT_FOUND
    travels through the same error-code-to-status table as classifier-origin errors. Asserted at the
    wire because the HTTP status is the assertion.
    """
    body = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"_meta": _meta_envelope()}}
    async with mounted_app(_server()) as (http, _):
        response = await http.post("/mcp", json=body, headers=_modern_headers(method="ping"))

    assert response.status_code == 404
    assert JSONRPCError.model_validate(response.json()).error.code == METHOD_NOT_FOUND


@requirement("hosting:http:modern:envelope-missing-key-status-400")
async def test_modern_envelope_missing_required_meta_key_is_invalid_params_at_http_400() -> None:
    """A 2026-07-28 request whose ``_meta`` envelope omits a required key is INVALID_PARAMS at HTTP 400.

    Spec-mandated under the draft transport: the per-request envelope must carry every reserved key,
    so a missing ``clientCapabilities`` fails the classifier's first rung before any kernel dispatch.
    Asserted at the wire because the HTTP status is the assertion.
    """
    incomplete = _meta_envelope()
    del incomplete[CLIENT_CAPABILITIES_META_KEY]
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": incomplete}}
    async with mounted_app(_server()) as (http, _):
        response = await http.post("/mcp", json=body, headers=_modern_headers(method="tools/list"))

    assert response.status_code == 400
    assert JSONRPCError.model_validate(response.json()).error.code == INVALID_PARAMS


@requirement("hosting:http:modern:handler-error-status-via-table")
async def test_modern_handler_raised_mcperror_maps_to_status_via_error_code_table() -> None:
    """A handler-raised ``MCPError`` reaches the wire as a top-level JSON-RPC error at the table-mapped HTTP status.

    SDK-defined for the HTTP status: the modern entry maps every JSON-RPC ``error.code`` -- whether
    classifier-origin or handler-origin -- through one error-code-to-status table, so a handler
    raising ``MISSING_REQUIRED_CLIENT_CAPABILITY`` produces HTTP 400 with ``error.data`` preserved.
    Spec-mandated for the error code: the named code and its ``requiredCapabilities`` data shape are
    the spec's capability-gating contract. Registered via the low-level ``add_request_handler`` so
    the high-level tool wrapper's error-swallowing is not on the path.
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
    """First end-to-end exercise of the 2026-07-28 stateless request style: SDK client to SDK server.

    Spec-mandated under the draft stateless transport: the pinned ``ClientSession`` and the
    single-exchange serving entry compose so that ``call_tool`` returns ``resultType: complete``
    with no ``initialize`` ever sent, no ``Mcp-Session-Id`` on any request or response, and every
    POST carrying the body-derived ``MCP-Protocol-Version`` / ``Mcp-Method`` / ``Mcp-Name`` headers
    plus the three-key ``io.modelcontextprotocol/*`` ``_meta`` envelope. The caller passes a
    ``custom-key`` under ``meta=`` and the server handler captures the incoming ``ctx.meta``,
    proving the envelope merge is additive: the caller's key sits alongside the three envelope keys
    on the wire and inside the handler. Asserted at the wire via the ``mounted_app`` httpx2 event
    hooks because none of the headers, the envelope, or the handshake-absence is observable through
    the public client API. The recorded log shows two POSTs: the ``tools/call`` itself and the
    client's implicit ``tools/list`` output-schema fetch (see ``client:output-schema:auto-list``),
    both of which must satisfy the stateless contract.
    """
    observed_metas: list[dict[str, Any]] = []
    server = _server(on_meta=observed_metas.append)

    requests: list[httpx2.Request] = []
    responses: list[httpx2.Response] = []

    async def on_request(request: httpx2.Request) -> None:
        requests.append(request)

    async def on_response(response: httpx2.Response) -> None:
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
    """A tools/call mirrors the tool's `x-mcp-header` arguments into `Mcp-Param-*` headers.

    After `list_tools` caches the tool's annotations, the client renders each annotated argument into
    its header per the spec's Value Encoding rules: `region` verbatim, `priority` as a decimal, `verbose`
    as `false`, and the non-ASCII `note` base64-sentinel-wrapped. The unannotated `query` and the omitted
    `verbose`-sibling stay out of the headers, and every mirrored value remains in the request body. Asserted
    at the wire because the client never surfaces the outgoing headers.
    """
    requests: list[httpx2.Request] = []

    async def on_request(request: httpx2.Request) -> None:
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
    """A `tools/call` for a tool the client never listed carries no `Mcp-Param-*` headers.

    The spec lets a client that lacks the tool's `inputSchema` send the request without custom headers.
    The call is made with no prior `list_tools`, so the first `tools/call` POST -- captured before the
    implicit output-schema `list_tools` runs -- has no cached annotations and emits no `Mcp-Param-*` header.
    """
    requests: list[httpx2.Request] = []

    async def on_request(request: httpx2.Request) -> None:
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
    """A re-list that drops a previously valid tool stops mirroring its `x-mcp-header` args.

    The tool is first listed with a valid annotation (so a call mirrors `Mcp-Param-Region`), then re-listed
    with an invalid annotation -- the modern client drops it and evicts the cached map, so a later `tools/call`
    by name carries no `Mcp-Param-*` header. Asserted at the wire, where the eviction is observable.
    """
    schema = {"type": "object", "properties": {"a": {"type": "string", "x-mcp-header": "Region"}}}
    bad_schema = {"type": "object", "properties": {"a": {"type": "string", "x-mcp-header": "bad name"}}}
    valid = Tool(name="run", input_schema=schema)
    invalid = Tool(name="run", input_schema=bad_schema)
    # Three pages: the call after the drop re-lists once because the prune also cleared `run`'s schema entry.
    listings = iter([valid, invalid, invalid])

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[next(listings)], ttl_ms=0, cache_scope="public")

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        return CallToolResult(content=[TextContent(text="ok")])

    server = Server("evict", on_list_tools=list_tools, on_call_tool=call_tool)

    tool_calls: list[httpx2.Request] = []

    async def on_request(request: httpx2.Request) -> None:
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
