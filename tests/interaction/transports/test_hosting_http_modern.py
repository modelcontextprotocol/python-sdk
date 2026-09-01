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
import httpx2
import pytest
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
    SERVER_INFO_META_KEY,
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
    JSONRPCNotification,
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
    jsonrpc_message_adapter,
)
from mcp_types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION
from starlette.datastructures import Headers
from starlette.requests import Request as StarletteRequest

from mcp import MCPError
from mcp.client import ClientRequestContext
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext
from mcp.shared.exceptions import NoBackChannelError
from tests._stamp import unstamped as strip_stamp
from tests.interaction._connect import (
    BASE_URL,
    base_headers,
    client_via_http,
    initialize_via_http,
    mounted_app,
    parse_sse_messages,
)
from tests.interaction._helpers import tool_listing
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
    """A low-level server with one `add` tool for the raw-httpx2 tests below.

    The explicit version gives the `_meta` serverInfo stamp every 2026 result
    carries a non-empty value for the wire-level snapshots.
    """

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

    return Server("modern", version="1.0.0", on_list_tools=list_tools, on_call_tool=call_tool)


@requirement("hosting:http:modern:tools-call-stateless")
@requirement("hosting:http:modern:lazy-sse-upgrade")
async def test_modern_tools_call_returns_result_type_complete_without_initialize() -> None:
    """A 2026-07-28 tools/call is served without an initialize handshake and returns resultType: complete.

    Spec-mandated under the draft transport: the per-request ``_meta`` envelope replaces initialize,
    `resultType` is the 2026 result-envelope discriminator (`complete` for the monolith
    result), and the server identifies itself via the result `_meta` serverInfo stamp. Asserted at
    the wire because the SDK client never surfaces `resultType` and because the absence of any
    prior request on the connection is the assertion. The `application/json` Content-Type also
    pins the lazy-upgrade JSON arm: a silent handler never commits SSE.
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
        {
            "content": [{"text": "5", "type": "text"}],
            "isError": False,
            "resultType": "complete",
            "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "modern", "version": "1.0.0"}},
        }
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


@requirement("hosting:http:modern:notification-post-202")
@pytest.mark.parametrize("json_response", [True, False], ids=["json", "sse"])
@pytest.mark.parametrize("stateless_http", [True, False], ids=["stateless-flag", "default"])
async def test_modern_notification_post_is_acknowledged_202_and_a_posted_response_is_rejected(
    json_response: bool, stateless_http: bool
) -> None:
    """A 2026-07-28 notification POST is answered 202 with no body; a posted response is 400 INVALID_REQUEST.

    Spec-permitted (streamable-http §Sending Messages item 5): the server may accept (202) or refuse
    (4xx) a notification POST, and the SDK accepts -- the same answer the legacy leg gives, so a
    client's courtesy `notifications/cancelled` is not met with an error on one era only.
    Spec-mandated (item 4): clients MUST NOT post responses, so one is refused. Driven through the
    mounted app so the manager's header routing is in the path, under both response modes and both
    values of the legacy-only `stateless_http` flag (neither is read before the modern entry answers).
    """
    notification = {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}}
    posted_response: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "result": {}}
    async with mounted_app(_server(), json_response=json_response, stateless_http=stateless_http) as (http, _):
        acknowledged = await http.post(
            "/mcp", json=notification, headers=_modern_headers(method="notifications/cancelled")
        )
        refused = await http.post("/mcp", json=posted_response, headers=_modern_headers(method="tools/list"))

    assert (acknowledged.status_code, acknowledged.content) == (202, b"")
    assert "mcp-session-id" not in acknowledged.headers
    assert refused.status_code == 400
    assert JSONRPCError.model_validate(refused.json()) == JSONRPCError(
        jsonrpc="2.0",
        id=None,
        error=ErrorData(code=INVALID_REQUEST, message="Body must be a single JSON-RPC request or notification object"),
    )


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
    """A 2026-07-28 server/discover POST returns capabilities and supportedVersions, with serverInfo in `_meta`.

    Spec-mandated under the draft: server/discover is the 2026 advertisement method that replaces
    the initialize-response payload, and ``supportedVersions`` is the field a client picks its
    per-request envelope version from. The server's identity is no longer a result-body field: it
    travels as the io.modelcontextprotocol/serverInfo result `_meta` stamp. Also pins the default
    `ttlMs 0` / `cacheScope private` hints stamped on the result. Asserted at the wire because
    the SDK client never exposes the raw result body.
    """
    body = {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": _meta_envelope()}}
    async with mounted_app(_server()) as (http, _):
        response = await http.post("/mcp", json=body, headers=_modern_headers(method="server/discover"))

    assert response.status_code == 200
    result = JSONRPCResponse.model_validate(response.json()).result
    assert result["supportedVersions"] == snapshot(["2026-07-28"])
    assert "serverInfo" not in result
    assert result["_meta"][SERVER_INFO_META_KEY] == {"name": "modern", "version": "1.0.0"}
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
            data={"requiredCapabilities": {"sampling": {}}},
        )

    server = _server()
    server.add_request_handler("test/cap-check", RequestParams, cap_check)
    body = {"jsonrpc": "2.0", "id": 1, "method": "test/cap-check", "params": {"_meta": _meta_envelope()}}
    async with mounted_app(server) as (http, _):
        response = await http.post("/mcp", json=body, headers=_modern_headers(method="test/cap-check"))

    assert response.status_code == 400
    error = JSONRPCError.model_validate(response.json()).error
    assert error.code == MISSING_REQUIRED_CLIENT_CAPABILITY
    assert error.data == {"requiredCapabilities": {"sampling": {}}}


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
                )
            )
            result = await session.call_tool(
                "add",
                {"a": 2, "b": 3},
                meta={"custom-key": "x", "io.modelcontextprotocol/protocolVersion": "evil"},
            )

    assert result.model_dump(by_alias=True, mode="json", exclude_none=True) == snapshot(
        {
            "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "modern", "version": "1.0.0"}},
            "content": [{"type": "text", "text": "5"}],
            "isError": False,
            "resultType": "complete",
        }
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


def _custom_header_server(*, on_call: Callable[[tuple[Headers, dict[str, Any] | None]], None] | None = None) -> Server:
    """A server with one tool whose schema annotates four args with `x-mcp-header` and leaves `query` plain.

    `on_call` observes the HTTP request headers and the arguments each tools/call reached the handler with.
    """

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[_CUSTOM_HEADER_TOOL], ttl_ms=0, cache_scope="public")

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        if on_call is not None:
            assert isinstance(ctx.request, StarletteRequest)
            on_call((ctx.request.headers, params.arguments))
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

    with anyio.fail_after(5):
        async with (
            mounted_app(_custom_header_server(), on_request=on_request) as (http, _),
            client_via_http(http, mode=LATEST_MODERN_VERSION) as client,
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
    requests: list[httpx2.Request] = []

    async def on_request(request: httpx2.Request) -> None:
        requests.append(request)

    with anyio.fail_after(5):
        async with (
            mounted_app(_custom_header_server(), on_request=on_request) as (http, _),
            client_via_http(http, mode=LATEST_MODERN_VERSION) as client,
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

    tool_calls: list[httpx2.Request] = []

    async def on_request(request: httpx2.Request) -> None:
        if json.loads(request.content)["method"] == "tools/call":
            tool_calls.append(request)

    with anyio.fail_after(5):
        async with (
            mounted_app(server, on_request=on_request) as (http, _),
            client_via_http(http, mode=LATEST_MODERN_VERSION) as client,
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

    requests: list[httpx2.Request] = []

    async def on_request(request: httpx2.Request) -> None:
        requests.append(request)

    with anyio.fail_after(5):
        async with (
            mounted_app(server, on_request=on_request) as (http, _),
            client_via_http(http, mode=LATEST_MODERN_VERSION) as client,
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

    Spec-mandated. The handler reads the header it was reached with from its HTTP request context;
    the round trip completing proves the server decoded the sentinel back to the body's name.
    """
    seen: list[str] = []

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "hëllo"
        assert isinstance(ctx.request, StarletteRequest)
        seen.append(ctx.request.headers["mcp-name"])
        return CallToolResult(content=[TextContent(text="ok")])

    server = Server("sentinel-name", on_list_tools=tool_listing("hëllo"), on_call_tool=call_tool)

    with anyio.fail_after(5):
        async with mounted_app(server) as (http, _), client_via_http(http, mode=LATEST_MODERN_VERSION) as client:
            result = await client.call_tool("hëllo", {})

    assert seen == ["=?base64?aMOrbGxv?="]
    assert strip_stamp(result) == snapshot(CallToolResult(content=[TextContent(text="ok")]))


@requirement("client-transport:http:custom-param-headers:sentinel-collision-escaped")
async def test_sentinel_lookalike_argument_value_is_base64_wrapped_in_its_param_header() -> None:
    """An argument value that itself matches ``=?base64?...?=`` is base64-wrapped in its param header.

    Spec-mandated by the sentinel-collision rule, the only encoding trigger: the value is otherwise
    header-safe ASCII. The handler records the header and the arguments it was reached with.
    """
    seen: list[tuple[Headers, dict[str, Any] | None]] = []
    arguments = {"region": "=?base64?literal?="}
    with anyio.fail_after(5):
        async with (
            mounted_app(_custom_header_server(on_call=seen.append)) as (http, _),
            client_via_http(http, mode=LATEST_MODERN_VERSION) as client,
        ):
            # Param mirroring requires the cached schema map, so list first.
            await client.list_tools()
            await client.call_tool("run", arguments)

    [(headers, received)] = seen
    assert headers["mcp-param-region"] == "=?base64?PT9iYXNlNjQ/bGl0ZXJhbD89?="
    assert received == arguments


@requirement("hosting:http:modern:mcp-param-null-absent-not-required")
@requirement("client-transport:http:custom-param-headers")
async def test_null_and_absent_annotated_arguments_emit_no_param_headers_and_the_server_accepts() -> None:
    """Null and absent annotated arguments emit no ``Mcp-Param-*`` headers and the server accepts the call.

    Spec-mandated by the behaviour matrix's null and absent rows. The fixture advertises the
    annotated schema, so this acceptance is a validated accept: the server checks each annotated
    argument against its `Mcp-Param-*` header and would reject an orphan header for the null or
    absent argument (a header matching no annotation is ignored).
    """
    seen: list[tuple[Headers, dict[str, Any] | None]] = []
    arguments = {"region": "us-west1", "note": None}
    with anyio.fail_after(5):
        async with (
            mounted_app(_custom_header_server(on_call=seen.append)) as (http, _),
            client_via_http(http, mode=LATEST_MODERN_VERSION) as client,
        ):
            # Param mirroring requires the cached schema map, so list first.
            await client.list_tools()
            result = await client.call_tool("run", arguments)

    assert strip_stamp(result) == snapshot(CallToolResult(content=[TextContent(text="ok")]))
    [(headers, received)] = seen
    assert {k: v for k, v in headers.items() if k.startswith("mcp-param-")} == {"mcp-param-region": "us-west1"}
    assert received == arguments


_LADDER_TOOL = Tool(
    name="run",
    input_schema={"type": "object", "properties": {"region": {"type": "string", "x-mcp-header": "Region"}}},
)


def _ladder_server() -> Server:
    """A server advertising the annotated `run` tool; every ladder rung is rejected before dispatch."""

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        raise NotImplementedError

    return Server("ladder", on_list_tools=tool_listing(_LADDER_TOOL), on_call_tool=call_tool)


def _call_body(**arguments: object) -> dict[str, object]:
    """A valid 2026-07-28 tools/call body for the ladder's `run` tool."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "run", "arguments": arguments, "_meta": _meta_envelope()},
    }


_STALE_ENVELOPE = {**_meta_envelope(), PROTOCOL_VERSION_META_KEY: LATEST_HANDSHAKE_VERSION}


@requirement("hosting:http:modern:std-header-mismatch-400")
@requirement("hosting:http:modern:missing-standard-header-rejected")
@requirement("hosting:http:modern:protocol-version-meta-mismatch-400")
@requirement("hosting:http:modern:mcp-param-mismatch-400")
@pytest.mark.parametrize(
    ("body", "headers", "expected_message"),
    [
        pytest.param(
            _call_body(),
            _modern_headers(method="tools/list", name="run"),
            "mcp-method header does not match the request body's method",
            id="method-lies",
        ),
        pytest.param(
            _call_body(),
            _modern_headers(method="tools/call", name="walk"),
            "mcp-name header does not match the request body's 'name' parameter",
            id="name-lies",
        ),
        pytest.param(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": _meta_envelope()}},
            base_headers() | {"mcp-protocol-version": LATEST_MODERN_VERSION},
            "mcp-method header does not match the request body's method",
            id="method-missing",
        ),
        pytest.param(
            _call_body(),
            _modern_headers(method="tools/call"),
            "mcp-name header does not match the request body's 'name' parameter",
            id="name-missing",
        ),
        pytest.param(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": _STALE_ENVELOPE}},
            _modern_headers(method="tools/list"),
            "mcp-protocol-version header does not match the request envelope's protocol version",
            id="version-disagrees",
        ),
        pytest.param(
            _call_body(region="us-west1"),
            _modern_headers(method="tools/call", name="run") | {"mcp-param-region": "eu-central1"},
            "Mcp-Param-Region header does not match the request body's 'region' argument",
            id="param-lies",
        ),
    ],
)
async def test_a_request_whose_mcp_headers_disagree_with_its_body_is_rejected_400_header_mismatch(
    body: dict[str, object], headers: dict[str, str], expected_message: str
) -> None:
    """Each rung of the SEP-2243 header ladder answers HTTP 400 + -32020 HeaderMismatch.

    Spec-mandated; only the varied header differs from a valid request, so the rejection provably
    comes from that rung. An absent header is reported through the mismatch check ("does not
    match"), and the messages are the SDK's own deliberate output. The version-disagrees envelope
    value is itself unsupported, so its -32020 also pins that the ladder runs before the version check.
    """
    with anyio.fail_after(5):
        async with mounted_app(_ladder_server()) as (http, _):
            response = await http.post("/mcp", json=body, headers=headers)

    assert response.status_code == 400
    error = JSONRPCError.model_validate(response.json()).error
    assert (error.code, error.message) == (HEADER_MISMATCH, expected_message)


@requirement("hosting:http:modern:cacheable-stamping")
@pytest.mark.parametrize(
    ("method", "params"),
    [("tools/list", {}), ("resources/list", {}), ("resources/read", {"uri": "res://x"})],
    ids=["tools-list", "resources-list", "resources-read"],
)
async def test_modern_cacheable_results_carry_ttl_and_scope_with_defaults_filled(
    method: str, params: dict[str, Any]
) -> None:
    """A 2026-07-28 cacheable result whose handler authored neither hint reaches the wire with
    resultType complete, the default ttlMs 0 / cacheScope private and the serverInfo stamp.

    Spec-mandated for the hints' presence; SDK-defined for the default values. The typed client
    default-fills the same values, so absent-versus-stamped is only visible at the wire.
    """

    async def list_resources(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListResourcesResult:
        return ListResourcesResult(resources=[])

    async def read_resource(ctx: ServerRequestContext, params: ReadResourceRequestParams) -> ReadResourceResult:
        return ReadResourceResult(contents=[TextResourceContents(uri=params.uri, text="hi")])

    server = Server(
        "cacheable", on_list_tools=tool_listing(), on_list_resources=list_resources, on_read_resource=read_resource
    )
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": {**params, "_meta": _meta_envelope()}}
    with anyio.fail_after(5):
        async with mounted_app(server) as (http, _):
            response = await http.post(
                "/mcp", json=body, headers=_modern_headers(method=method, name=params.get("uri"))
            )

    assert response.status_code == 200
    result = JSONRPCResponse.model_validate(response.json()).result
    assert result["resultType"] == "complete"
    assert result["ttlMs"] == 0
    assert result["cacheScope"] == "private"
    assert result["_meta"][SERVER_INFO_META_KEY]["name"] == "cacheable"


@requirement("hosting:http:modern:json-response-mode")
async def test_modern_json_response_mode_returns_single_json_body_and_drops_mid_call_notifications() -> None:
    """In JSON response mode a 2026-07-28 request gets one application/json body; mid-call emits are dropped.

    SDK-defined. The one body is the only place a buffered notification could surface, and it is
    the bare response. The emit passes ``related_request_id`` so the drop pinned is the json-mode
    drop, not the no-channel drop the connection's outbound would apply anyway.
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
    payload = response.json()
    assert set(payload) == {"jsonrpc", "id", "result"}
    assert payload["id"] == 1
    assert payload["result"]["content"][0]["text"] == "done"


async def _post_modern(
    http: httpx2.AsyncClient, body: dict[str, Any], *, method: str, name: str | None = None
) -> tuple[httpx2.Response, list[JSONRPCMessage]]:
    """POST a 2026-07-28 request and collect the JSON-RPC messages its response carried.

    A silent handler is answered with one JSON body; a handler that emits mid-call upgrades the
    response to an SSE stream, so both representations are read.
    """
    async with http.stream("POST", "/mcp", json=body, headers=_modern_headers(method=method, name=name)) as response:
        if response.headers["content-type"].split(";", 1)[0] == "application/json":
            messages = [jsonrpc_message_adapter.validate_json(await response.aread())]
        else:
            messages = parse_sse_messages([event async for event in httpx2.EventSource(response)])
    return response, messages


@requirement("hosting:http:modern:lazy-sse-upgrade")
async def test_modern_response_upgrades_to_sse_when_the_handler_emits_and_ends_with_the_result() -> None:
    """On the default mode, a mid-call emit upgrades the response to SSE and the result is the last frame.

    SDK-defined framing; the silent-handler JSON arm is pinned by the stateless tools/call test
    above. The interval after which a silent handler commits to SSE anyway is deliberately unpinned.
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
        async with mounted_app(Server("modern", on_call_tool=call_tool)) as (http, _):
            response, messages = await _post_modern(http, body, method="tools/call", name="noisy")

    assert response.status_code == 200
    assert response.headers["content-type"].split(";", 1)[0] == "text/event-stream"
    notification, final = messages
    assert isinstance(notification, JSONRPCNotification) and notification.method == "notifications/progress"
    assert isinstance(final, JSONRPCResponse)


@requirement("hosting:http:modern:response-stream-request-scoped")
async def test_modern_notifications_land_only_on_the_originating_requests_response_stream() -> None:
    """A notification emitted while serving one request travels only on that request's response stream.

    Spec-mandated. The interleaving is structural: "quiet" parks mid-handler, "emit" sends its
    notification while quiet is provably in flight, then releases it; a broadcast or misroute
    would have added a frame to quiet's response or upgraded it to SSE.
    """
    quiet_started = anyio.Event()
    release_quiet = anyio.Event()

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        if params.name == "emit":
            await quiet_started.wait()
            await ctx.session.send_notification(
                ProgressNotification(params=ProgressNotificationParams(progress_token="t", progress=1)),
                related_request_id=ctx.request_id,
            )
            release_quiet.set()
            return CallToolResult(content=[TextContent(text="emitted")])
        assert params.name == "quiet"
        quiet_started.set()
        await release_quiet.wait()
        return CallToolResult(content=[TextContent(text="quiet-done")])

    server = Server("scoped", on_call_tool=call_tool)
    streams: dict[str, tuple[httpx2.Response, list[JSONRPCMessage]]] = {}

    async def post(http: httpx2.AsyncClient, request_id: int, tool: str) -> None:
        body = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": {}, "_meta": _meta_envelope()},
        }
        streams[tool] = await _post_modern(http, body, method="tools/call", name=tool)

    with anyio.fail_after(5):
        async with mounted_app(server) as (http, _), anyio.create_task_group() as tg:
            tg.start_soon(post, http, 1, "emit")
            tg.start_soon(post, http, 2, "quiet")

    emit_response, emit_messages = streams["emit"]
    quiet_response, quiet_messages = streams["quiet"]
    assert emit_response.headers["content-type"].split(";", 1)[0] == "text/event-stream"
    assert [type(m) for m in emit_messages] == [JSONRPCNotification, JSONRPCResponse]
    assert quiet_response.headers["content-type"].split(";", 1)[0] == "application/json"
    assert [type(m) for m in quiet_messages] == [JSONRPCResponse]


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
            http.sse(
                "/mcp", method="POST", json=body, headers=_modern_headers(method="tools/call", name="noisy")
            ) as source,
        ):
            # Drained only so teardown is clean.
            async for _ in source:
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
    assert JSONRPCResponse.model_validate(response.json()).result["content"] == [{"type": "text", "text": "5"}]


@requirement("hosting:http:modern:sentinel-decoded-before-validation")
async def test_modern_client_non_ascii_prompt_name_round_trips_via_sentinel_encoded_header() -> None:
    """A non-ASCII prompt name travels sentinel-encoded on the Mcp-Name header and is served, because the
    server decodes the header before validating it against the body's name.

    Spec-mandated. The handler reads the header it was reached with from its HTTP request context.
    """
    seen: list[str] = []

    async def get_prompt(ctx: ServerRequestContext, params: GetPromptRequestParams) -> GetPromptResult:
        assert params.name == "héllo"
        assert isinstance(ctx.request, StarletteRequest)
        seen.append(ctx.request.headers["mcp-name"])
        return GetPromptResult(messages=[PromptMessage(role="user", content=TextContent(text="bonjour"))])

    server = Server("sentinel-prompt", on_get_prompt=get_prompt)

    with anyio.fail_after(5):
        async with mounted_app(server) as (http, _), client_via_http(http, mode=LATEST_MODERN_VERSION) as client:
            result = await client.get_prompt("héllo")

    assert seen == ["=?base64?aMOpbGxv?="]
    assert strip_stamp(result) == snapshot(
        GetPromptResult(messages=[PromptMessage(role="user", content=TextContent(text="bonjour"))])
    )


@requirement("mrtr:push-api:loud-fail-2026")
async def test_modern_request_scoped_push_elicit_loud_fails_locally_and_the_call_still_completes() -> None:
    """A request-scoped push elicit over the modern HTTP entry loud-fails locally and the call still completes.

    Spec-mandated outcome: the modern HTTP entry builds its per-request channel with no
    back-channel, so the refusal is local by construction. The in-memory twin of this leg is
    pinned in lowlevel/test_mrtr.py; this pin keeps the HTTP entry's own gate regression-covered.
    """
    caught: list[NoBackChannelError] = []

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

    server = Server("scoped-push", on_list_tools=tool_listing("ask"), on_call_tool=call_tool)

    # Declares the elicitation capability, isolating the failure to the missing back-channel.
    async def never_deliverable(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        raise NotImplementedError

    with anyio.fail_after(5):
        async with (
            mounted_app(server) as (http, _),
            client_via_http(http, mode=LATEST_MODERN_VERSION, elicitation_callback=never_deliverable) as client,
        ):
            result = await client.call_tool("ask", {})

    assert strip_stamp(result) == snapshot(CallToolResult(content=[TextContent(text="fallback")]))
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
