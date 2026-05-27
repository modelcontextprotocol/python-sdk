"""Streamable HTTP semantics: status codes, header validation, message routing, and security.

These tests speak HTTP directly to the server's mounted ASGI app via the in-process bridge,
asserting the wire contract -- which status code answers which condition, which stream a message
travels on -- that the SDK client never exposes. Transport-agnostic behaviour is covered by the
`connect`-fixture matrix.
"""

import anyio
import pytest
from anyio.lowlevel import checkpoint
from httpx_sse import ServerSentEvent, aconnect_sse
from inline_snapshot import snapshot

from mcp.server import Server, ServerRequestContext
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import (
    INVALID_PARAMS,
    PARSE_ERROR,
    CallToolRequestParams,
    CallToolResult,
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
)
from tests.interaction._connect import (
    base_headers,
    initialize_body,
    initialize_via_http,
    mounted_app,
    parse_sse_messages,
)
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


def _server() -> Server:
    """A low-level server with one tool that emits a related and an unrelated notification."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        """Registered only so the tools capability is advertised; never called."""
        raise NotImplementedError

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "narrate"
        await ctx.session.send_log_message(level="info", data="related", logger=None, related_request_id=ctx.request_id)
        await ctx.session.send_resource_updated("file:///watched.txt")
        return CallToolResult(content=[TextContent(text="done")])

    return Server("hosted", on_list_tools=list_tools, on_call_tool=call_tool)


@requirement("hosting:http:method-405")
async def test_unsupported_http_methods_return_405() -> None:
    """PUT and PATCH on the MCP endpoint return 405 with an Allow header naming the supported methods."""
    async with mounted_app(_server()) as (http, _):
        session_id = await initialize_via_http(http)
        put = await http.put("/mcp", json={}, headers=base_headers(session_id=session_id))
        patch = await http.patch("/mcp", json={}, headers=base_headers(session_id=session_id))

    assert (put.status_code, put.headers.get("allow")) == snapshot((405, "GET, POST, DELETE"))
    assert (patch.status_code, patch.headers.get("allow")) == snapshot((405, "GET, POST, DELETE"))


@requirement("hosting:http:accept-406")
async def test_missing_accept_media_types_return_406() -> None:
    """A POST whose Accept header lacks both required types, or a GET lacking text/event-stream, returns 406."""
    async with mounted_app(_server()) as (http, _):
        post = await http.post(
            "/mcp", json=initialize_body(), headers={"accept": "text/plain", "mcp-protocol-version": "2025-11-25"}
        )
        session_id = await initialize_via_http(http)
        get = await http.get(
            "/mcp",
            headers={"accept": "application/json", "mcp-protocol-version": "2025-11-25", "mcp-session-id": session_id},
        )

    assert (post.status_code, post.json()["error"]["message"]) == snapshot(
        (406, "Not Acceptable: Client must accept both application/json and text/event-stream")
    )
    assert (get.status_code, get.json()["error"]["message"]) == snapshot(
        (406, "Not Acceptable: Client must accept text/event-stream")
    )


@requirement("hosting:http:content-type-415")
async def test_non_json_content_type_is_rejected() -> None:
    """A POST with a non-JSON Content-Type is rejected before reaching the transport.

    See the divergence on the requirement: the security middleware rejects with 400, so the
    transport's own 415 path is unreachable through any public entry point.
    """
    async with mounted_app(_server()) as (http, _):
        response = await http.post(
            "/mcp", content=b"<not-json/>", headers=base_headers() | {"content-type": "text/plain"}
        )

    assert (response.status_code, response.text) == snapshot((400, "Invalid Content-Type header"))


@requirement("hosting:http:parse-error-400")
@requirement("hosting:http:batch")
async def test_malformed_and_batched_bodies_return_400() -> None:
    """A non-JSON body returns 400 Parse error; a JSON array of requests returns 400 Invalid params."""
    async with mounted_app(_server()) as (http, _):
        session_id = await initialize_via_http(http)
        not_json = await http.post(
            "/mcp",
            content=b"this is not json",
            headers=base_headers(session_id=session_id) | {"content-type": "application/json"},
        )
        batched = await http.post(
            "/mcp",
            json=[
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            ],
            headers=base_headers(session_id=session_id),
        )

    assert not_json.status_code == 400
    assert JSONRPCError.model_validate_json(not_json.text).error.code == PARSE_ERROR
    assert batched.status_code == 400
    assert JSONRPCError.model_validate_json(batched.text).error.code == INVALID_PARAMS


@requirement("hosting:http:protocol-version-400")
@requirement("hosting:http:protocol-version-default")
async def test_protocol_version_header_is_validated() -> None:
    """An unsupported MCP-Protocol-Version header returns 400; an absent header is accepted as the default."""
    async with mounted_app(_server()) as (http, _):
        session_id = await initialize_via_http(http)

        bad = await http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers=base_headers(session_id=session_id) | {"mcp-protocol-version": "1991-01-01"},
        )
        # Only Accept and the session ID -- no MCP-Protocol-Version header at all.
        defaulted = await http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progressToken": 0, "progress": 1}},
            headers={"accept": "application/json, text/event-stream", "mcp-session-id": session_id},
        )

    assert bad.status_code == 400
    assert JSONRPCError.model_validate_json(bad.text).error.message.startswith(
        "Bad Request: Unsupported protocol version: 1991-01-01."
    )
    # 202 proves the request was accepted under the assumed default version (2025-03-26).
    assert defaulted.status_code == 202


@requirement("hosting:http:notifications-202")
async def test_notification_post_returns_202_with_no_body() -> None:
    """A POST containing only a notification (no request ID) returns 202 Accepted with no body."""
    async with mounted_app(_server()) as (http, _):
        session_id = await initialize_via_http(http)
        response = await http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progressToken": 0, "progress": 1}},
            headers=base_headers(session_id=session_id),
        )

    assert (response.status_code, response.content) == snapshot((202, b""))


@requirement("hosting:http:second-sse-rejected")
async def test_a_second_standalone_get_stream_on_the_same_session_returns_409() -> None:
    """Opening a second standalone GET SSE stream while one is already established returns 409 Conflict."""
    async with mounted_app(_server()) as (http, _):
        session_id = await initialize_via_http(http)

        async with aconnect_sse(http, "GET", "/mcp", headers=base_headers(session_id=session_id)) as first:
            assert first.response.status_code == 200
            # The standalone-stream writer registers its key as its first action, then parks
            # awaiting messages; one yield to the loop lets that registration complete before the
            # second GET is dispatched.
            await checkpoint()
            second = await http.get("/mcp", headers=base_headers(session_id=session_id))

    assert (second.status_code, second.json()["error"]["message"]) == snapshot(
        (409, "Conflict: Only one SSE stream is allowed per session")
    )


@requirement("hosting:http:standalone-sse")
@requirement("hosting:http:standalone-sse-no-response")
@requirement("hosting:http:response-same-connection")
@requirement("hosting:http:sse-close-after-response")
@requirement("hosting:http:no-broadcast")
async def test_messages_are_routed_to_exactly_one_stream() -> None:
    """Each server message travels on exactly one SSE stream and is never broadcast.

    A streamable-HTTP session has two kinds of server-to-client SSE stream: one short-lived stream
    per POST request, carrying that request's response and any notifications related to it, and one
    long-lived standalone stream (opened by GET) for notifications not tied to any request. The
    spec's routing rule is that the POST stream delivers the response (and its related
    notifications) and then closes, the standalone stream carries only unrelated notifications and
    never a JSON-RPC response, and no message appears on both. The test opens both streams, calls a
    tool whose handler emits one related and one unrelated notification, and asserts each message's
    routing.
    """
    async with mounted_app(_server()) as (http, _):
        session_id = await initialize_via_http(http)
        post_events: list[ServerSentEvent] = []
        get_events: list[ServerSentEvent] = []

        async def read_standalone_stream() -> None:
            async with aconnect_sse(http, "GET", "/mcp", headers=base_headers(session_id=session_id)) as get:
                assert get.response.status_code == 200
                standalone_ready.set()
                async for event in get.aiter_sse():
                    get_events.append(event)
                    seen_on_standalone.set()

        standalone_ready = anyio.Event()
        seen_on_standalone = anyio.Event()
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:
                tg.start_soon(read_standalone_stream)
                await standalone_ready.wait()

                params = CallToolRequestParams(name="narrate", arguments={})
                body = JSONRPCRequest(jsonrpc="2.0", id=5, method="tools/call", params=params.model_dump())
                async with aconnect_sse(
                    http,
                    "POST",
                    "/mcp",
                    json=body.model_dump(by_alias=True, exclude_none=True),
                    headers=base_headers(session_id=session_id),
                ) as post:
                    assert post.response.status_code == 200
                    # The POST stream iterator ends when the server closes the stream after the response.
                    post_events = [event async for event in post.aiter_sse()]

                await seen_on_standalone.wait()
                tg.cancel_scope.cancel()

    post_messages = parse_sse_messages(post_events)
    get_messages = parse_sse_messages(get_events)

    # POST stream: the related log notification, then the response, then the iterator ends (close).
    assert [type(m).__name__ for m in post_messages] == snapshot(["JSONRPCNotification", "JSONRPCResponse"])
    assert isinstance(post_messages[0], JSONRPCNotification)
    assert (post_messages[0].method, post_messages[0].params) == snapshot(
        ("notifications/message", {"level": "info", "data": "related"})
    )
    assert isinstance(post_messages[1], JSONRPCResponse)
    assert post_messages[1].id == 5

    # Standalone stream: only the unrelated resource-updated notification, never a response.
    assert [type(m).__name__ for m in get_messages] == snapshot(["JSONRPCNotification"])
    assert isinstance(get_messages[0], JSONRPCNotification)
    assert get_messages[0].method == snapshot("notifications/resources/updated")


@requirement("hosting:http:dns-rebinding")
@requirement("transport:streamable-http:origin-validation")
async def test_origin_validation_rejects_disallowed_origins_when_enabled() -> None:
    """A disallowed Origin returns 403 (and Host 421) with protection enabled; disabled lets both through.

    See the divergence on hosting:http:dns-rebinding: the spec's Origin validation is an
    unconditional MUST, but the SDK enables it only when the host is localhost (or settings are
    passed explicitly) and additionally checks the Host header (returning 421), which the spec
    does not require.
    """
    # transport_security=None triggers the localhost auto-enable behaviour.
    async with mounted_app(Server("guarded"), transport_security=None) as (http, _):
        bad_origin = await http.post(
            "/mcp", json=initialize_body(), headers=base_headers() | {"origin": "http://evil.example"}
        )
        bad_host = await http.post("/mcp", json=initialize_body(), headers=base_headers() | {"host": "evil.example"})
        async with aconnect_sse(
            http, "POST", "/mcp", json=initialize_body(), headers=base_headers() | {"origin": "http://127.0.0.1:8000"}
        ) as ok:
            assert ok.response.status_code == 200
            assert [event async for event in ok.aiter_sse()]

    assert (bad_origin.status_code, bad_origin.text) == snapshot((403, "Invalid Origin header"))
    assert (bad_host.status_code, bad_host.text) == snapshot((421, "Invalid Host header"))

    async with mounted_app(
        Server("unguarded"), transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)
    ) as (http, _):
        async with aconnect_sse(
            http, "POST", "/mcp", json=initialize_body(), headers=base_headers() | {"origin": "http://evil.example"}
        ) as unguarded:
            status = unguarded.response.status_code
            assert [event async for event in unguarded.aiter_sse()]

    assert status == 200
