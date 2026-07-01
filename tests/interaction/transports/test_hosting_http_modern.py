"""Streamable HTTP at protocol version 2026-07-28: the single-exchange stateless serving entry.

These tests speak HTTP directly to the server's mounted ASGI app via the in-process bridge,
asserting the wire contract for a 2026-07-28 POST -- one self-contained request, no initialize
handshake, no ``Mcp-Session-Id``, JSON response body -- and that 2025-era traffic on the same
endpoint is byte-unchanged. The SDK client never exposes the response headers or the raw
result-envelope shape, so every assertion here is necessarily wire-level. A few tests drive the SDK client instead.
"""

import json
from collections.abc import Callable
from typing import Any, Literal

import anyio
import httpx
import pytest
from httpx_sse import aconnect_sse
from inline_snapshot import snapshot
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    HEADER_MISMATCH,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    PROTOCOL_VERSION_META_KEY,
    CallToolRequestParams,
    CallToolResult,
    DiscoverResult,
    ElicitRequestParams,
    ElicitResult,
    EmptyResult,
    ErrorData,
    GetPromptRequestParams,
    GetPromptResult,
    Implementation,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCResponse,
    ListResourcesResult,
    ListToolsResult,
    PaginatedRequestParams,
    ProgressNotification,
    ProgressNotificationParams,
    PromptMessage,
    ReadResourceRequestParams,
    ReadResourceResult,
    Request,
    RequestParams,
    Result,
    ServerCapabilities,
    TextContent,
    TextResourceContents,
    Tool,
)
from mcp_types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION
from starlette.requests import Request as StarletteRequest

from mcp import MCPError
from mcp.client import ClientRequestContext
from mcp.client.client import Client
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext
from mcp.shared.exceptions import NoBackChannelError
from tests.interaction._connect import (
    BASE_URL,
    base_headers,
    client_via_http,
    initialize_via_http,
    mounted_app,
    parse_sse_messages,
)
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
@requirement("hosting:http:modern:lazy-sse-upgrade")
async def test_modern_tools_call_returns_result_type_complete_without_initialize() -> None:
    """A 2026-07-28 tools/call is served without an initialize handshake and returns resultType: complete.

    Spec-mandated under the draft transport: the per-request ``_meta`` envelope replaces initialize,
    and ``resultType`` is the 2026 result-envelope discriminator (``complete`` for the monolith
    result). Asserted at the wire because the SDK client never surfaces ``resultType`` and because
    the absence of any prior request on the connection is the assertion. The ``application/json``
    Content-Type also pins the lazy-upgrade JSON arm: a silent handler never commits SSE.
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
@requirement("lifecycle:version:dual-era-precedence")
async def test_modern_initialize_is_method_not_found() -> None:
    """A 2026-07-28 initialize request that carries a valid envelope is answered METHOD_NOT_FOUND at HTTP 404.

    Spec-mandated under the draft: initialize is not a defined method at 2026-07-28, so the kernel's
    method/version gate rejects it before any handler runs. The body must carry the per-request
    ``_meta`` envelope so the classifier ladder admits it as far as kernel dispatch -- without the
    envelope the request is INVALID_PARAMS at rung 1, never METHOD_NOT_FOUND. Asserted at the wire
    because the SDK client at 2026-07-28 never sends initialize, so only a raw POST can drive the
    negative. Also pins dual-era precedence: this frame is simultaneously a valid modern envelope
    and the legacy handshake opener, and the rejection proves the modern classification won.
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
@requirement("caching:hints:server-discover")
async def test_modern_server_discover_returns_capabilities_and_supported_versions() -> None:
    """A 2026-07-28 server/discover POST returns capabilities, serverInfo, and supportedVersions.

    Spec-mandated under the draft: server/discover is the 2026 advertisement method that replaces
    the initialize-response payload, and ``supportedVersions`` is the field a client picks its
    per-request envelope version from. Also pins the default ``ttlMs 0`` / ``cacheScope private``
    hints stamped on the result. Asserted at the wire because the SDK client never exposes
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
    assert result["resultType"] == "complete"
    assert result["ttlMs"] == 0
    assert result["cacheScope"] == "private"


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
    """A `tools/call` for a tool the client never listed carries no `Mcp-Param-*` headers.

    The spec lets a client that lacks the tool's `inputSchema` send the request without custom headers.
    The call is made with no prior `list_tools`, so the first `tools/call` POST -- captured before the
    implicit output-schema `list_tools` runs -- has no cached annotations and emits no `Mcp-Param-*` header.
    The server validates `Mcp-Param-*` against its own catalog and rejects as the spec's scenario table
    requires for an omitted header (the relist-and-retry recovery is a SHOULD the client does not implement yet).
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
            with pytest.raises(MCPError) as excinfo:  # pragma: no branch
                await client.call_tool("run", {"region": "us-west1"})

    assert excinfo.value.error.code == HEADER_MISMATCH
    assert len(requests) == 1
    assert json.loads(requests[0].content)["method"] == "tools/call"
    assert not any(k.startswith("mcp-param-") for k in requests[0].headers)


@requirement("client-transport:http:custom-param-headers")
async def test_modern_client_stops_mirroring_after_a_re_list_drops_the_tool() -> None:
    """A re-list that drops a previously valid tool stops mirroring its `x-mcp-header` args.

    The tool is first listed with a valid annotation (so a call mirrors `Mcp-Param-Region`), then re-listed
    with an invalid annotation -- the modern client drops it and evicts the cached map, so a later `tools/call`
    by name carries no `Mcp-Param-*` header. The server serves that header-less call only because the same
    invalid schema disables its own validation (the shared validator skips schemas it rejects); a valid
    annotated schema would reject the missing header. Asserted at the wire, where the eviction is observable.
    """
    schema = {"type": "object", "properties": {"a": {"type": "string", "x-mcp-header": "Region"}}}
    bad_schema = {"type": "object", "properties": {"a": {"type": "string", "x-mcp-header": "bad name"}}}
    valid = Tool(name="run", input_schema=schema)
    invalid = Tool(name="run", input_schema=bad_schema)
    # First listing valid, every later one invalid; the count is not pinned because the server also
    # reads its own catalog on each tools/call.
    listings: list[None] = []

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        listings.append(None)
        return ListToolsResult(tools=[valid if len(listings) == 1 else invalid], ttl_ms=0, cache_scope="public")

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


class _JobParams(RequestParams):
    job_id: str


class _JobStatusRequest(Request[_JobParams, Literal["com.example/jobs.status"]]):
    method: Literal["com.example/jobs.status"] = "com.example/jobs.status"
    name_param = "jobId"


class _JobStatusResult(Result):
    status: str


@requirement("client-transport:http:vendor-name-param-header")
async def test_vendor_request_with_name_param_carries_mcp_name_on_the_wire() -> None:
    """`send_request` mirrors an unregistered vendor request's `name_param` value into the
    `Mcp-Name` header while the body keeps the params key unchanged."""

    async def job_status(ctx: ServerRequestContext, params: _JobParams) -> _JobStatusResult:
        assert params.job_id == "job-7"
        return _JobStatusResult(status="running")

    server = _server()
    server.add_request_handler("com.example/jobs.status", _JobParams, job_status)

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
            mounted_app(server, on_request=on_request) as (http, _),
            Client(
                streamable_http_client(f"{BASE_URL}/mcp", http_client=http),
                mode=LATEST_MODERN_VERSION,
                prior_discover=discover,
            ) as client,
        ):
            request = _JobStatusRequest(params=_JobParams(job_id="job-7"))
            result = await client.session.send_request(request, _JobStatusResult)

    assert result.status == "running"
    [wire_request] = requests
    assert wire_request.headers["mcp-name"] == "job-7"
    assert json.loads(wire_request.content)["params"]["jobId"] == "job-7"


@requirement("client-transport:http:mcp-name-base64-sentinel")
async def test_non_header_safe_tool_name_is_carried_as_base64_sentinel_mcp_name() -> None:
    """A tools/call for a non-header-safe tool name carries ``Mcp-Name`` in the base64 sentinel form.

    Spec-mandated. No prior ``list_tools``, so the header is derived from the request body, not a
    cached schema; the round trip completing proves the server decoded the sentinel.
    """

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        # Live: the client's implicit output-schema refresh calls tools/list.
        return ListToolsResult(tools=[Tool(name="hëllo", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "hëllo"
        return CallToolResult(content=[TextContent(text="ok")])

    server = Server("sentinel-name", on_list_tools=list_tools, on_call_tool=call_tool)

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
            mounted_app(server, on_request=on_request) as (http, _),
            Client(
                streamable_http_client(f"{BASE_URL}/mcp", http_client=http),
                mode=LATEST_MODERN_VERSION,
                prior_discover=discover,
            ) as client,
        ):
            result = await client.call_tool("hëllo", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="ok")]))
    call = next(r for r in requests if json.loads(r.content)["method"] == "tools/call")
    assert call.headers["mcp-name"] == snapshot("=?base64?aMOrbGxv?=")
    assert json.loads(call.content)["params"]["name"] == "hëllo"


@requirement("client-transport:http:custom-param-headers:sentinel-collision-escaped")
async def test_sentinel_lookalike_argument_value_is_base64_wrapped_in_its_param_header() -> None:
    """An argument value that itself matches ``=?base64?...?=`` is base64-wrapped in its param header.

    Spec-mandated by the sentinel-collision rule, the only encoding trigger: the value is otherwise header-safe ASCII.
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
            # Param mirroring requires the cached schema map, so list first.
            await client.list_tools()
            await client.call_tool("run", {"region": "=?base64?literal?="})

    call = next(r for r in requests if json.loads(r.content)["method"] == "tools/call")
    assert {k: v for k, v in call.headers.items() if k.startswith("mcp-param-")} == snapshot(
        {"mcp-param-region": "=?base64?PT9iYXNlNjQ/bGl0ZXJhbD89?="}
    )
    assert json.loads(call.content)["params"]["arguments"] == {"region": "=?base64?literal?="}


@requirement("hosting:http:modern:mcp-param-null-absent-not-required")
@requirement("client-transport:http:custom-param-headers")
async def test_null_and_absent_annotated_arguments_emit_no_param_headers_and_the_server_accepts() -> None:
    """Null and absent annotated arguments emit no ``Mcp-Param-*`` headers and the server accepts the call.

    Spec-mandated by the behaviour matrix's null and absent rows. The fixture advertises the
    annotated schema, so this acceptance is a validated accept: the server checks each annotated
    argument against its `Mcp-Param-*` header and would reject an orphan header for the null or
    absent argument (a header matching no annotation is ignored).
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
            # Param mirroring requires the cached schema map, so list first.
            await client.list_tools()
            result = await client.call_tool("run", {"region": "us-west1", "note": None})

    assert result == snapshot(CallToolResult(content=[TextContent(text="ok")]))
    call = next(r for r in requests if json.loads(r.content)["method"] == "tools/call")
    assert {k: v for k, v in call.headers.items() if k.startswith("mcp-param-")} == snapshot(
        {"mcp-param-region": "us-west1"}
    )
    assert json.loads(call.content)["params"]["arguments"] == {"region": "us-west1", "note": None}


@requirement("hosting:http:modern:std-header-mismatch-400")
async def test_modern_mcp_method_header_disagreeing_with_body_method_is_rejected_400_header_mismatch() -> None:
    """A ``Mcp-Method`` header disagreeing with the body's method is rejected with HTTP 400 and HeaderMismatch.

    Spec-mandated; everything else on the request is valid, so the rejection provably comes from the Mcp-Method rung.
    """
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "add", "arguments": {"a": 2, "b": 3}, "_meta": _meta_envelope()},
    }
    with anyio.fail_after(5):
        async with mounted_app(_server()) as (http, _):
            response = await http.post("/mcp", json=body, headers=_modern_headers(method="tools/list", name="add"))

    assert response.status_code == 400
    assert JSONRPCError.model_validate(response.json()).error == snapshot(
        ErrorData(code=HEADER_MISMATCH, message="mcp-method header does not match the request body's method")
    )


@requirement("hosting:http:modern:std-header-mismatch-400")
async def test_modern_mcp_name_header_disagreeing_with_body_name_is_rejected_400_header_mismatch() -> None:
    """A ``Mcp-Name`` header disagreeing with the body's name parameter is rejected with HTTP 400 and HeaderMismatch.

    Spec-mandated: the Mcp-Name arm of the same MUST as the test above, a distinct rung with its own message.
    """
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "add", "arguments": {"a": 2, "b": 3}, "_meta": _meta_envelope()},
    }
    with anyio.fail_after(5):
        async with mounted_app(_server()) as (http, _):
            response = await http.post("/mcp", json=body, headers=_modern_headers(method="tools/call", name="subtract"))

    assert response.status_code == 400
    assert JSONRPCError.model_validate(response.json()).error == snapshot(
        ErrorData(code=HEADER_MISMATCH, message="mcp-name header does not match the request body's 'name' parameter")
    )


@requirement("hosting:http:modern:cacheable-stamping")
async def test_modern_cacheable_results_carry_ttl_and_scope_with_defaults_filled() -> None:
    """A 2026-07-28 cacheable result reaches the wire as resultType complete plus the ttlMs/cacheScope hints.

    Spec-mandated for the hints' presence; SDK-defined for the fill: authored values pass through
    (tools/list), unauthored gets the defaults (resources/list), partial fills only the missing
    hint (resources/read). The typed client default-fills, so the stamp is only visible at the wire.
    """

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(
            tools=[Tool(name="add", input_schema={"type": "object"})], ttl_ms=60_000, cache_scope="public"
        )

    async def list_resources(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListResourcesResult:
        # Neither hint set: the wire values are the SDK's default fill.
        return ListResourcesResult(resources=[])

    async def read_resource(ctx: ServerRequestContext, params: ReadResourceRequestParams) -> ReadResourceResult:
        assert params.uri == "res://x"
        return ReadResourceResult(contents=[TextResourceContents(uri="res://x", text="hi")], ttl_ms=5_000)

    server = Server(
        "cacheable", on_list_tools=list_tools, on_list_resources=list_resources, on_read_resource=read_resource
    )

    with anyio.fail_after(5):
        async with mounted_app(server) as (http, _):
            listed_tools = await http.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": _meta_envelope()}},
                headers=_modern_headers(method="tools/list"),
            )
            listed_resources = await http.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "resources/list", "params": {"_meta": _meta_envelope()}},
                headers=_modern_headers(method="resources/list"),
            )
            # resources/read is name-bearing on its uri param: without Mcp-Name the ladder 400s.
            read = await http.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "resources/read",
                    "params": {"uri": "res://x", "_meta": _meta_envelope()},
                },
                headers=_modern_headers(method="resources/read", name="res://x"),
            )

    assert listed_tools.status_code == 200
    assert JSONRPCResponse.model_validate(listed_tools.json()).result == snapshot(
        {
            "cacheScope": "public",
            "resultType": "complete",
            "tools": [{"inputSchema": {"type": "object"}, "name": "add"}],
            "ttlMs": 60000,
        }
    )
    assert listed_resources.status_code == 200
    assert JSONRPCResponse.model_validate(listed_resources.json()).result == snapshot(
        {"cacheScope": "private", "resources": [], "resultType": "complete", "ttlMs": 0}
    )
    assert read.status_code == 200
    assert JSONRPCResponse.model_validate(read.json()).result == snapshot(
        {
            "cacheScope": "private",
            "contents": [{"text": "hi", "uri": "res://x"}],
            "resultType": "complete",
            "ttlMs": 5000,
        }
    )


@requirement("hosting:http:modern:json-response-mode")
async def test_modern_json_response_mode_returns_single_json_body_and_drops_mid_call_notifications() -> None:
    """In JSON response mode a 2026-07-28 request gets one application/json body; mid-call emits are dropped.

    SDK-defined. The full-body snapshot is both proofs: the one body is the only place a buffered
    notification could surface. The emit passes ``related_request_id`` so the drop pinned is the
    json-mode drop, not the no-channel drop the connection's outbound would apply anyway.
    """

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "noisy"
        await ctx.session.send_notification(
            ProgressNotification(params=ProgressNotificationParams(progress_token="t", progress=1)),
            related_request_id=ctx.request_id,
        )
        return CallToolResult(content=[TextContent(text="done")])

    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "noisy", "arguments": {}, "_meta": _meta_envelope()},
    }
    with anyio.fail_after(5):
        async with mounted_app(Server("modern", on_call_tool=call_tool), json_response=True) as (http, _):
            response = await http.post("/mcp", json=body, headers=_modern_headers(method="tools/call", name="noisy"))

    assert response.status_code == 200
    assert response.headers["content-type"].split(";", 1)[0] == "application/json"
    assert response.json() == snapshot(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"text": "done", "type": "text"}], "isError": False, "resultType": "complete"},
        }
    )


@requirement("hosting:http:modern:lazy-sse-upgrade")
async def test_modern_response_upgrades_to_sse_when_the_handler_emits_and_ends_with_the_result() -> None:
    """On the default mode, mid-call emits upgrade the response to SSE with the result as the last frame.

    SDK-defined framing; the snapshot's length is the nothing-after-the-result proof, and the
    silent-handler JSON arm is pinned by the stateless tools/call test above. The deferral window
    before a silent handler commits SSE is deliberately unpinned (needs a real-time wait).
    """

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "noisy"
        for progress in (1, 2):
            await ctx.session.send_notification(
                ProgressNotification(params=ProgressNotificationParams(progress_token="t", progress=progress)),
                related_request_id=ctx.request_id,
            )
        return CallToolResult(content=[TextContent(text="done")])

    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "noisy", "arguments": {}, "_meta": _meta_envelope()},
    }
    with anyio.fail_after(5):
        async with (
            mounted_app(Server("modern", on_call_tool=call_tool)) as (http, _),
            aconnect_sse(
                http, "POST", "/mcp", json=body, headers=_modern_headers(method="tools/call", name="noisy")
            ) as source,
        ):
            events = [event async for event in source.aiter_sse()]

    assert source.response.status_code == 200
    assert source.response.headers["content-type"].split(";", 1)[0] == "text/event-stream"
    assert [
        m.model_dump(by_alias=True, mode="json", exclude_none=True) for m in parse_sse_messages(events)
    ] == snapshot(
        [
            {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progressToken": "t", "progress": 1.0}},
            {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progressToken": "t", "progress": 2.0}},
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": [{"text": "done", "type": "text"}], "isError": False, "resultType": "complete"},
            },
        ]
    )


@requirement("hosting:http:modern:response-stream-request-scoped")
async def test_modern_notifications_land_only_on_the_originating_requests_response_stream() -> None:
    """A notification emitted while serving one request travels only on that request's response stream.

    Spec-mandated. The interleaving is structural: "quiet" parks mid-handler, "emit" sends its
    notification while quiet is provably in flight, then releases it; a broadcast or misroute
    would have committed quiet's still-uncommitted response to SSE or added a frame.
    """
    quiet_started = anyio.Event()
    release_quiet = anyio.Event()

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        if params.name == "emit":
            with anyio.fail_after(5):
                await quiet_started.wait()
            await ctx.session.send_notification(
                ProgressNotification(params=ProgressNotificationParams(progress_token="t", progress=1)),
                related_request_id=ctx.request_id,
            )
            release_quiet.set()
            return CallToolResult(content=[TextContent(text="emitted")])
        assert params.name == "quiet"
        quiet_started.set()
        with anyio.fail_after(5):
            await release_quiet.wait()
        return CallToolResult(content=[TextContent(text="quiet-done")])

    server = Server("scoped", on_call_tool=call_tool)

    emit_responses: list[httpx.Response] = []
    emit_frames: list[JSONRPCMessage] = []
    quiet_responses: list[httpx.Response] = []

    async def post_emit(http: httpx.AsyncClient) -> None:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "emit", "arguments": {}, "_meta": _meta_envelope()},
        }
        async with aconnect_sse(
            http, "POST", "/mcp", json=body, headers=_modern_headers(method="tools/call", name="emit")
        ) as source:
            events = [event async for event in source.aiter_sse()]
            emit_responses.append(source.response)
            emit_frames.extend(parse_sse_messages(events))

    async def post_quiet(http: httpx.AsyncClient) -> None:
        body = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "quiet", "arguments": {}, "_meta": _meta_envelope()},
        }
        quiet_responses.append(
            await http.post("/mcp", json=body, headers=_modern_headers(method="tools/call", name="quiet"))
        )

    with anyio.fail_after(5):
        async with (
            mounted_app(server) as (http, _),
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(post_emit, http)
            tg.start_soon(post_quiet, http)

    [sse_response] = emit_responses
    assert sse_response.headers["content-type"].split(";", 1)[0] == "text/event-stream"
    assert [m.model_dump(by_alias=True, mode="json", exclude_none=True) for m in emit_frames] == snapshot(
        [
            {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progressToken": "t", "progress": 1.0}},
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "content": [{"text": "emitted", "type": "text"}],
                    "isError": False,
                    "resultType": "complete",
                },
            },
        ]
    )
    [json_response] = quiet_responses
    assert json_response.headers["content-type"].split(";", 1)[0] == "application/json"
    assert json_response.json() == snapshot(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"text": "quiet-done", "type": "text"}], "isError": False, "resultType": "complete"},
        }
    )


@requirement("hosting:http:sse-x-accel-buffering")
async def test_modern_sse_response_carries_x_accel_buffering_no() -> None:
    """A 2026-07-28 response that commits to an SSE stream carries ``X-Accel-Buffering: no``.

    Spec-recommended so proxies deliver events unbuffered; the Content-Type assert guards a vacuous pass.
    """

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "noisy"
        await ctx.session.send_notification(
            ProgressNotification(params=ProgressNotificationParams(progress_token="t", progress=1)),
            related_request_id=ctx.request_id,
        )
        return CallToolResult(content=[TextContent(text="done")])

    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "noisy", "arguments": {}, "_meta": _meta_envelope()},
    }
    with anyio.fail_after(5):
        async with (
            mounted_app(Server("modern", on_call_tool=call_tool)) as (http, _),
            aconnect_sse(
                http, "POST", "/mcp", json=body, headers=_modern_headers(method="tools/call", name="noisy")
            ) as source,
        ):
            # Drained only so teardown is clean.
            async for _ in source.aiter_sse():
                pass

    assert source.response.headers["x-accel-buffering"] == "no"
    assert source.response.headers["content-type"].split(";", 1)[0] == "text/event-stream"


@requirement("hosting:http:modern:header-name-case-insensitive")
async def test_modern_standard_headers_are_matched_case_insensitively() -> None:
    """Standard request headers sent under any casing are served, not rejected as missing.

    Spec-mandated. The bridge lowercases header names into the ASGI scope, so the pinned claim is
    that the server's lookups key on the lowercase canonical names, not on any cased spelling.
    """
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "add", "arguments": {"a": 2, "b": 3}, "_meta": _meta_envelope()},
    }
    # Hand-built: a union with base_headers() would keep its lowercase mcp-protocol-version key
    # alongside the cased spelling, breaking the no-lowercase-spelling-anywhere premise.
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "MCP-PROTOCOL-VERSION": LATEST_MODERN_VERSION,
        "MCP-METHOD": "tools/call",
        "McP-NaMe": "add",
    }
    with anyio.fail_after(5):
        async with mounted_app(_server()) as (http, _):
            response = await http.post("/mcp", json=body, headers=headers)

    assert response.status_code == 200
    parsed = JSONRPCResponse.model_validate(response.json())
    assert parsed.id == 1
    assert parsed.result == snapshot(
        {"content": [{"text": "5", "type": "text"}], "isError": False, "resultType": "complete"}
    )


@requirement("hosting:http:modern:missing-standard-header-rejected")
async def test_modern_request_missing_mcp_method_header_is_header_mismatch_at_http_400() -> None:
    """A 2026-07-28 request missing the ``Mcp-Method`` header is rejected with HTTP 400 and HeaderMismatch.

    Spec-mandated. The rejection comes through the mismatch rung (absent header != body method),
    so the message says "does not match" rather than "missing" -- covered by the spec, not a divergence.
    """
    # tools/list is non-name-bearing, so the omitted Mcp-Method is the only missing header.
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": _meta_envelope()}}
    headers = base_headers() | {"mcp-protocol-version": LATEST_MODERN_VERSION}
    with anyio.fail_after(5):
        async with mounted_app(_server()) as (http, _):
            response = await http.post("/mcp", json=body, headers=headers)

    assert response.status_code == 400
    error = JSONRPCError.model_validate(response.json()).error
    assert error.code == HEADER_MISMATCH
    assert error.message == snapshot("mcp-method header does not match the request body's method")


@requirement("hosting:http:modern:missing-standard-header-rejected")
async def test_modern_name_bearing_request_missing_mcp_name_header_is_header_mismatch_at_http_400() -> None:
    """A name-bearing request missing the ``Mcp-Name`` header is rejected with HTTP 400 and HeaderMismatch.

    Spec-mandated. The body's ``name`` is present while the header is absent (a name-less body is the spec's lenience).
    """
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "add", "arguments": {"a": 2, "b": 3}, "_meta": _meta_envelope()},
    }
    with anyio.fail_after(5):
        async with mounted_app(_server()) as (http, _):
            # _modern_headers omits Mcp-Name when no name is given: valid except the one header.
            response = await http.post("/mcp", json=body, headers=_modern_headers(method="tools/call"))

    assert response.status_code == 400
    error = JSONRPCError.model_validate(response.json()).error
    assert error.code == HEADER_MISMATCH
    assert error.message == snapshot("mcp-name header does not match the request body's 'name' parameter")


@requirement("hosting:http:modern:protocol-version-meta-mismatch-400")
async def test_modern_protocol_version_header_envelope_disagreement_is_header_mismatch_at_http_400() -> None:
    """Individually valid but disagreeing header and envelope protocol versions are rejected 400 HeaderMismatch.

    Spec-mandated, and the mismatch rung runs before the supported-version check: the envelope
    value is deliberately unsupported, so the snapshot pins the rung order for free.
    """
    envelope = _meta_envelope()
    envelope[PROTOCOL_VERSION_META_KEY] = LATEST_HANDSHAKE_VERSION
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": envelope}}
    with anyio.fail_after(5):
        async with mounted_app(_server()) as (http, _):
            response = await http.post("/mcp", json=body, headers=_modern_headers(method="tools/list"))

    assert response.status_code == 400
    error = JSONRPCError.model_validate(response.json()).error
    assert error.code == HEADER_MISMATCH
    assert error.message == snapshot(
        "mcp-protocol-version header does not match the request envelope's protocol version"
    )


@requirement("hosting:http:modern:sentinel-decoded-before-validation")
async def test_modern_encoded_mcp_name_matching_the_body_after_decode_is_served() -> None:
    """A sentinel-encoded ``Mcp-Name`` whose decoded value matches the body is served, not rejected.

    Spec-mandated: the server decodes the header before validation -- a plain string comparison
    would have answered 400 HeaderMismatch. The typed client sends ASCII bare, hence raw httpx.
    """
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "add", "arguments": {"a": 2, "b": 3}, "_meta": _meta_envelope()},
    }
    headers = _modern_headers(method="tools/call") | {"mcp-name": "=?base64?YWRk?="}
    with anyio.fail_after(5):
        async with mounted_app(_server()) as (http, _):
            response = await http.post("/mcp", json=body, headers=headers)

    assert response.status_code == 200
    parsed = JSONRPCResponse.model_validate(response.json())
    assert parsed.id == 1
    assert parsed.result == snapshot(
        {"content": [{"text": "5", "type": "text"}], "isError": False, "resultType": "complete"}
    )


@requirement("hosting:http:modern:sentinel-decoded-before-validation")
async def test_modern_client_non_ascii_prompt_name_round_trips_via_sentinel_encoded_header() -> None:
    """A non-ASCII prompt name round-trips end to end, travelling sentinel-encoded on the Mcp-Name header.

    Spec-mandated. The recorded request proves the header on the wire really was the sentinel
    form; ``prompts/get`` is name-bearing with no implicit follow-up traffic, so exactly one POST.
    """

    async def get_prompt(ctx: ServerRequestContext, params: GetPromptRequestParams) -> GetPromptResult:
        assert params.name == "héllo"
        return GetPromptResult(messages=[PromptMessage(role="user", content=TextContent(text="bonjour"))])

    server = Server("sentinel-prompt", on_get_prompt=get_prompt)

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
            mounted_app(server, on_request=on_request) as (http, _),
            Client(
                streamable_http_client(f"{BASE_URL}/mcp", http_client=http),
                mode=LATEST_MODERN_VERSION,
                prior_discover=discover,
            ) as client,
        ):
            result = await client.get_prompt("héllo")

    assert result == snapshot(
        GetPromptResult(messages=[PromptMessage(role="user", content=TextContent(text="bonjour"))])
    )
    [call] = requests
    assert json.loads(call.content)["method"] == "prompts/get"
    assert call.headers["mcp-name"] == snapshot("=?base64?aMOpbGxv?=")
    assert json.loads(call.content)["params"]["name"] == "héllo"


@requirement("hosting:http:modern:disconnect-cancels-handler")
async def test_modern_client_disconnect_mid_request_cancels_the_running_handler() -> None:
    """Closing the SSE response stream mid-request cancels the running handler.

    Spec-mandated: the disconnect is the transport-level cancellation signal. The handler emits
    one notification first so a committed stream exists to close; the "no response is written"
    clause holds by construction (a cancelled handler never produces a result).
    """
    handler_cancelled = anyio.Event()

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "park"
        await ctx.session.send_notification(
            ProgressNotification(params=ProgressNotificationParams(progress_token="t", progress=1)),
            related_request_id=ctx.request_id,
        )
        try:
            # Parked with no normal exit: transport cancellation is the only way out.
            while True:
                await anyio.sleep_forever()
        except anyio.get_cancelled_exc_class():
            handler_cancelled.set()
            raise

    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "park", "arguments": {}, "_meta": _meta_envelope()},
    }
    with anyio.fail_after(5):
        async with mounted_app(Server("modern", on_call_tool=call_tool)) as (http, _):
            async with aconnect_sse(
                http, "POST", "/mcp", json=body, headers=_modern_headers(method="tools/call", name="park")
            ) as source:
                # Advanced once only: a full `async for` would wait for the close that is ours to perform.
                events = source.aiter_sse()
                first = await anext(events)
            # Awaited while the app is still mounted: after mounted_app exits, the bridge's
            # teardown cancellation would make this pass vacuously.
            await handler_cancelled.wait()

    [first_frame] = parse_sse_messages([first])
    assert first_frame.model_dump(by_alias=True, mode="json", exclude_none=True) == snapshot(
        {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progressToken": "t", "progress": 1.0}}
    )


@requirement("mrtr:push-api:loud-fail-2026")
async def test_modern_request_scoped_push_elicit_loud_fails_locally_and_the_call_still_completes() -> None:
    """A request-scoped push elicit over the modern HTTP entry loud-fails locally and the call still completes.

    Spec-mandated outcome; the enforcement here is incidental (no back-channel, not an era gate).
    The in-memory twin of this leg still transmits the frame -- the divergence pinned in
    lowlevel/test_mrtr.py -- so the modern entry's gate gets its own regression pin.
    """
    caught: list[NoBackChannelError] = []

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        # Live: the client's implicit output-schema refresh calls tools/list.
        return ListToolsResult(tools=[Tool(name="ask", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask"
        assert ctx.request_id is not None
        try:
            # The related id selects the per-request dispatch channel.
            await ctx.session.elicit_form(
                "Need a name",
                {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
                related_request_id=ctx.request_id,
            )
        except NoBackChannelError as exc:
            caught.append(exc)
        return CallToolResult(content=[TextContent(text="fallback")])

    server = Server("scoped-push", on_list_tools=list_tools, on_call_tool=call_tool)

    # Declares the elicitation capability, isolating the failure to the missing back-channel.
    async def never_deliverable(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        raise NotImplementedError

    discover = DiscoverResult(
        supported_versions=[LATEST_MODERN_VERSION],
        capabilities=ServerCapabilities(),
        server_info=Implementation(name="srv", version="0"),
    )
    with anyio.fail_after(5):
        async with (
            mounted_app(server) as (http, _),
            Client(
                streamable_http_client(f"{BASE_URL}/mcp", http_client=http),
                mode=LATEST_MODERN_VERSION,
                prior_discover=discover,
                elicitation_callback=never_deliverable,
            ) as client,
        ):
            result = await client.call_tool("ask", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="fallback")]))
    assert len(caught) == 1
    assert caught[0].method == "elicitation/create"
    assert caught[0].error == snapshot(
        ErrorData(
            code=INVALID_REQUEST,
            message=(
                "Cannot send 'elicitation/create': this transport context has no back-channel "
                "for server-initiated requests."
            ),
        )
    )


@requirement("hosting:http:request-headers-in-handler")
async def test_custom_request_header_reaches_the_handler_request_context_on_both_serving_paths() -> None:
    """A custom HTTP header sent by the client reaches the handler's ctx.request on both serving paths.

    SDK-defined. The per-leg values are distinct so a failure names the broken path; each leg
    builds a fresh server because a session manager only runs once.
    """

    def probe_server() -> Server:
        async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
            # Live: call_tool's implicit output-schema fetch lists.
            return ListToolsResult(tools=[Tool(name="probe", input_schema={"type": "object"})])

        async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
            assert params.name == "probe"
            assert isinstance(ctx.request, StarletteRequest)
            return CallToolResult(content=[TextContent(text=ctx.request.headers.get("x-probe", "<missing>"))])

        return Server("header-probe", on_list_tools=list_tools, on_call_tool=call_tool)

    discover = DiscoverResult(
        supported_versions=[LATEST_MODERN_VERSION],
        capabilities=ServerCapabilities(),
        server_info=Implementation(name="srv", version="0"),
    )
    with anyio.fail_after(5):
        async with (
            mounted_app(probe_server(), headers={"x-probe": "modern-value"}) as (http, _),
            Client(
                streamable_http_client(f"{BASE_URL}/mcp", http_client=http),
                mode=LATEST_MODERN_VERSION,
                prior_discover=discover,
            ) as client,
        ):
            modern_result = await client.call_tool("probe", {})

    with anyio.fail_after(5):
        async with (
            mounted_app(probe_server(), headers={"x-probe": "legacy-value"}) as (http, _),
            client_via_http(http) as client,
        ):
            legacy_result = await client.call_tool("probe", {})

    assert modern_result == snapshot(CallToolResult(content=[TextContent(text="modern-value")]))
    assert legacy_result == snapshot(CallToolResult(content=[TextContent(text="legacy-value")]))


@requirement("hosting:http:modern:mcp-param-mismatch-400")
async def test_modern_mcp_param_header_disagreeing_with_body_argument_is_rejected_400_header_mismatch() -> None:
    """A ``Mcp-Param-*`` header disagreeing with its body argument is rejected with HTTP 400 and HeaderMismatch.

    Spec-mandated: the server resolves the ``x-mcp-header`` annotation from the tool's advertised
    ``inputSchema`` via its own tools/list handler and rejects the decoded-header/body disagreement
    before dispatch. Raw httpx because the HTTP status is a wire-only observable and the typed
    client cannot emit a mismatching header by construction.
    """

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        tool = Tool(
            name="run",
            input_schema={"type": "object", "properties": {"region": {"type": "string", "x-mcp-header": "Region"}}},
        )
        return ListToolsResult(tools=[tool])

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        raise NotImplementedError  # The mismatch is rejected before dispatch reaches the handler.

    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "run", "arguments": {"region": "us-west1"}, "_meta": _meta_envelope()},
    }
    headers = _modern_headers(method="tools/call", name="run") | {"mcp-param-region": "eu-central1"}
    with anyio.fail_after(5):
        async with mounted_app(Server("param-mismatch", on_list_tools=list_tools, on_call_tool=call_tool)) as (
            http,
            _,
        ):
            response = await http.post("/mcp", json=body, headers=headers)

    assert response.status_code == 400
    assert JSONRPCError.model_validate(response.json()).error == snapshot(
        ErrorData(
            code=HEADER_MISMATCH, message="Mcp-Param-Region header does not match the request body's 'region' argument"
        )
    )
