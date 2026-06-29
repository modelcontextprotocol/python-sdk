"""Unit tests for the 2026-07-28 single-exchange HTTP serving entry.

The interaction suite (tests/interaction/transports/test_hosting_http_modern.py) pins the wire
contract end to end; these tests cover the internal seams: the dispatch context's closed
back-channel and `handle_modern_request`'s validation ladder.
"""

import json
import logging
from typing import Any

import anyio
import httpx
import pytest
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    HEADER_MISMATCH,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    PROTOCOL_VERSION_META_KEY,
    ErrorData,
    JSONRPCError,
    JSONRPCResponse,
    ListToolsResult,
    LoggingMessageNotification,
    LoggingMessageNotificationParams,
    PaginatedRequestParams,
    Tool,
)
from mcp_types.version import LATEST_MODERN_VERSION
from starlette.types import Message, Receive, Scope, Send
from trio.testing import MockClock

from mcp.server import Server, ServerRequestContext, runner
from mcp.server._streamable_http_modern import (
    _SingleExchangeDispatchContext,
    _to_jsonrpc_response,
    handle_modern_request,
)
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError, NoBackChannelError
from mcp.shared.inbound import MCP_METHOD_HEADER, MCP_NAME_HEADER, MCP_PROTOCOL_VERSION_HEADER
from mcp.shared.transport_context import TransportContext
from tests.interaction.transports import StreamingASGITransport

pytestmark = pytest.mark.anyio


async def test_single_exchange_dispatch_context_has_no_back_channel() -> None:
    """Without an SSE sink, notify/progress are no-ops and server-initiated requests raise."""
    dctx = _SingleExchangeDispatchContext(
        transport=TransportContext(kind="streamable-http", can_send_request=False),
        request_id=1,
        message_metadata=None,
    )
    assert dctx.can_send_request is False
    with pytest.raises(NoBackChannelError):
        await dctx.send_raw_request("roots/list", None)
    assert await dctx.notify("notifications/message", None) is None
    assert await dctx.progress(0.5, total=1.0, message="half") is None


def _asgi_client(
    server: Server[Any],
    security_settings: TransportSecuritySettings | None = None,
    *,
    json_response: bool = True,
    accept: str = "application/json, text/event-stream",
) -> httpx.AsyncClient:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        async with server.lifespan(server) as lifespan_state:
            await handle_modern_request(server, security_settings, json_response, lifespan_state, scope, receive, send)

    return httpx.AsyncClient(
        transport=StreamingASGITransport(app),
        base_url="http://testserver",
        headers={
            MCP_PROTOCOL_VERSION_HEADER: LATEST_MODERN_VERSION,
            "content-type": "application/json",
            "accept": accept,
        },
    )


async def test_handle_modern_request_rejects_non_post_with_http_405_and_allow_header() -> None:
    """SDK-defined: rejected at the HTTP layer per RFC 9110, before JSON-RPC parsing, so no body."""
    async with _asgi_client(Server("test")) as http:
        response = await http.get("/mcp")
    assert response.status_code == 405
    assert response.headers["allow"] == "POST"
    assert response.content == b""


async def test_handle_modern_request_rejects_a_notification_body_with_invalid_request() -> None:
    """SDK-defined: well-formed JSON that isn't a request object (no `id`) is INVALID_REQUEST, not PARSE_ERROR."""
    async with _asgi_client(Server("test")) as http:
        response = await http.post(
            "/mcp",
            content=b'{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":1}}',
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == INVALID_REQUEST


async def test_handle_modern_request_rejects_malformed_body_with_parse_error() -> None:
    """The 400 status is SDK-defined (error-code→HTTP-status table); the `id: null` error body is spec-mandated."""
    async with _asgi_client(Server("test")) as http:
        response = await http.post("/mcp", content=b"not json", headers={"content-type": "application/json"})
    assert response.status_code == 400
    assert response.headers["content-type"].split(";", 1)[0] == "application/json"
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": PARSE_ERROR, "message": "Parse error"},
    }


async def test_handle_modern_request_returns_transport_security_error_response() -> None:
    settings = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["good.example"])
    async with _asgi_client(Server("test"), security_settings=settings) as http:
        response = await http.post("/mcp", json={}, headers={"content-type": "application/json"})
    assert response.status_code == 421
    assert response.text == "Invalid Host header"


def _list_tools_body() -> dict[str, Any]:
    """Minimal valid 2026-07-28 `tools/list` body with the required `_meta` envelope."""
    meta = {
        PROTOCOL_VERSION_META_KEY: LATEST_MODERN_VERSION,
        CLIENT_INFO_META_KEY: {"name": "raw", "version": "0.0.0"},
        CLIENT_CAPABILITIES_META_KEY: {},
    }
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta}}


async def test_handle_modern_request_routes_with_mis_shaped_envelope_client_info() -> None:
    """SDK-defined: a mis-shaped `clientInfo` envelope is treated as absent; the handler sees
    `client_params is None`. A non-spec method keeps the kernel's per-method params validation
    from re-rejecting the envelope."""
    seen: list[object] = []

    async def greet(ctx: ServerRequestContext, params: PaginatedRequestParams) -> dict[str, Any]:
        seen.append(ctx.session.client_params)
        return {"ok": True}

    server: Server[Any] = Server("test")
    server.add_request_handler("custom/greet", PaginatedRequestParams, greet)

    body = _list_tools_body()
    body["method"] = "custom/greet"
    body["params"]["_meta"][CLIENT_INFO_META_KEY] = "not-an-object"
    async with _asgi_client(server) as http:
        response = await http.post("/mcp", json=body, headers={MCP_METHOD_HEADER: "custom/greet"})
    assert response.status_code == 200
    assert response.json()["result"] == {"ok": True}
    assert seen == [None]


async def test_handle_modern_request_sends_response_when_exit_stack_cleanup_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The exit-stack guard is `aclose_shielded`: cleanup runs in `serve_one`'s finally and a raise
    there must not displace the already-built response."""

    async def boom() -> None:
        raise RuntimeError("cleanup failed")

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        ctx.session._connection.exit_stack.push_async_callback(boom)
        return ListToolsResult(tools=[], ttl_ms=0, cache_scope="public")

    with caplog.at_level(logging.ERROR, logger=runner.__name__):
        async with _asgi_client(Server("test", on_list_tools=list_tools)) as http:
            response = await http.post("/mcp", json=_list_tools_body(), headers={MCP_METHOD_HEADER: "tools/list"})

    assert response.status_code == 200
    assert response.json()["result"]["tools"] == []
    assert "connection exit_stack cleanup raised" in caplog.text


async def test_handle_modern_request_sends_response_when_exit_stack_cleanup_hangs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Grace patched to 0 so the deadline is expired on entry: the bounded unwind cancels the blocker
    at its first checkpoint and the already-built response still ships."""
    monkeypatch.setattr(runner, "_EXIT_STACK_CLOSE_TIMEOUT", 0)

    async def block() -> None:
        await anyio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        ctx.session._connection.exit_stack.push_async_callback(block)
        return ListToolsResult(tools=[], ttl_ms=0, cache_scope="public")

    with anyio.fail_after(5), caplog.at_level(logging.WARNING, logger=runner.__name__):
        async with _asgi_client(Server("test", on_list_tools=list_tools)) as http:
            response = await http.post("/mcp", json=_list_tools_body(), headers={MCP_METHOD_HEADER: "tools/list"})
    # coverage.py on Python 3.11 misreports these lines as unhit; the shielded-cancel path disrupts the tracer here.
    assert response.status_code == 200  # pragma: lax no cover
    assert response.json()["result"]["tools"] == []  # pragma: lax no cover
    assert "abandoning remaining callbacks" in caplog.text  # pragma: lax no cover


async def test_to_jsonrpc_response_wraps_success_as_jsonrpc_response() -> None:
    """SDK-defined: the awaited dict ships verbatim as `result` under the supplied id."""

    async def ok() -> dict[str, Any]:
        return {"k": "v"}

    reply = await _to_jsonrpc_response(7, ok())
    assert isinstance(reply, JSONRPCResponse)
    assert reply.id == 7
    assert reply.result == {"k": "v"}


async def test_to_jsonrpc_response_maps_mcp_error_to_jsonrpc_error() -> None:
    """SDK-defined: the `MCPError`'s code, message, and data carry through to the `error` object."""

    async def fail() -> dict[str, Any]:
        raise MCPError(code=METHOD_NOT_FOUND, message="nope", data="x")

    reply = await _to_jsonrpc_response("rid", fail())
    assert isinstance(reply, JSONRPCError)
    assert reply.id == "rid"
    assert reply.error == ErrorData(code=METHOD_NOT_FOUND, message="nope", data="x")


async def test_to_jsonrpc_response_maps_validation_error_to_invalid_params() -> None:
    """SDK-defined: validator detail never reaches the wire — only a generic INVALID_PARAMS message."""

    async def fail() -> dict[str, Any]:
        Tool.model_validate({"name": 123})  # raises ValidationError
        raise NotImplementedError

    reply = await _to_jsonrpc_response(1, fail())
    assert isinstance(reply, JSONRPCError)
    assert reply.error == ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data="")


async def test_to_jsonrpc_response_maps_unmapped_exception_to_internal_error_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SDK-defined: an unmapped exception is logged server-side and surfaced as a generic INTERNAL_ERROR."""

    async def fail() -> dict[str, Any]:
        raise RuntimeError("boom")

    reply = await _to_jsonrpc_response(1, fail())
    assert isinstance(reply, JSONRPCError)
    assert reply.error.code == INTERNAL_ERROR
    # Handler internals never reach the wire.
    assert "boom" not in reply.error.message
    assert "request handler raised" in caplog.text


async def test_handle_modern_request_rejects_mismatched_method_header_with_400_and_header_mismatch() -> None:
    """Spec-mandated: rejected at the boundary; the handler never runs."""
    async with _asgi_client(Server("test")) as http:
        response = await http.post("/mcp", json=_list_tools_body(), headers={MCP_METHOD_HEADER: "prompts/list"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == HEADER_MISMATCH


async def test_handle_modern_request_rejects_mismatched_name_header_with_400_and_header_mismatch() -> None:
    """Spec-mandated: `Mcp-Name` must match the body's named param for name-bearing methods."""
    body = _list_tools_body()
    body["method"] = "tools/call"
    body["params"]["name"] = "real"
    body["params"]["arguments"] = {}
    async with _asgi_client(Server("test")) as http:
        response = await http.post(
            "/mcp", json=body, headers={MCP_METHOD_HEADER: "tools/call", MCP_NAME_HEADER: "wrong"}
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == HEADER_MISMATCH


def _sse_payloads(body: str) -> list[dict[str, Any]]:
    """Parse an SSE body into the list of JSON `data:` payloads, in delivery order."""
    return [
        json.loads(line.removeprefix("data:").strip())
        for line in body.replace("\r\n", "\n").splitlines()
        if line.startswith("data:")
    ]


def _list_tools_body_with_token(token: str | int) -> dict[str, Any]:
    body = _list_tools_body()
    body["params"]["_meta"]["progressToken"] = token
    return body


async def test_sse_mode_streams_progress_then_result() -> None:
    """Spec-mandated: progress events carry the caller's token and precede the terminal response;
    Content-Type and event order are the wire contract."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        await ctx.session.report_progress(1.0, total=3.0)
        await ctx.session.report_progress(2.0, total=3.0, message="almost")
        return ListToolsResult(tools=[], ttl_ms=0, cache_scope="public")

    async with _asgi_client(Server("test", on_list_tools=list_tools), json_response=False) as http:
        with anyio.fail_after(5):
            response = await http.post(
                "/mcp", json=_list_tools_body_with_token("tok-1"), headers={MCP_METHOD_HEADER: "tools/list"}
            )

    assert response.status_code == 200
    assert response.headers["content-type"].split(";", 1)[0] == "text/event-stream"
    events = _sse_payloads(response.text)
    assert len(events) == 3
    assert events[0] == {
        "jsonrpc": "2.0",
        "method": "notifications/progress",
        "params": {"progressToken": "tok-1", "progress": 1.0, "total": 3.0},
    }
    assert events[1] == {
        "jsonrpc": "2.0",
        "method": "notifications/progress",
        "params": {"progressToken": "tok-1", "progress": 2.0, "total": 3.0, "message": "almost"},
    }
    assert events[2]["id"] == 1
    assert events[2]["result"]["tools"] == []


@pytest.mark.parametrize(
    "anyio_backend",
    [pytest.param(("trio", {"clock": MockClock(autojump_threshold=0)}), id="trio-mockclock")],
)
async def test_sse_mode_emits_keepalive_comment_between_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """SDK-defined: an idle stream emits SSE comments so a proxy idle-read timeout doesn't kill the
    handler. Trio's autojumping MockClock advances the ping deadlines without wall-clock time."""
    monkeypatch.setattr("mcp.server._streamable_http_modern._SSE_PING_INTERVAL", 1.0)

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        await ctx.session.report_progress(1.0)
        await anyio.sleep(2.5)
        return ListToolsResult(tools=[], ttl_ms=0, cache_scope="public")

    async with _asgi_client(Server("test", on_list_tools=list_tools), json_response=False) as http:
        with anyio.fail_after(5):
            response = await http.post(
                "/mcp", json=_list_tools_body_with_token("tok"), headers={MCP_METHOD_HEADER: "tools/list"}
            )

    assert response.headers["content-type"].split(";", 1)[0] == "text/event-stream"
    assert response.content.count(b": ping\r\n\r\n") == 2
    events = _sse_payloads(response.text)
    assert len(events) == 2
    assert events[0]["method"] == "notifications/progress"
    assert events[1]["result"]["tools"] == []


@pytest.mark.parametrize(
    "anyio_backend",
    [pytest.param(("trio", {"clock": MockClock(autojump_threshold=0)}), id="trio-mockclock")],
)
async def test_sse_mode_silent_handler_commits_sse_after_ping_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    """SDK-defined: a handler silent past the deferral window (bounded by `_SSE_PING_INTERVAL`) still
    commits `text/event-stream` and pings, so a proxy idle-read timeout doesn't kill it."""
    monkeypatch.setattr("mcp.server._streamable_http_modern._SSE_PING_INTERVAL", 1.0)

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        await anyio.sleep(2.5)
        return ListToolsResult(tools=[], ttl_ms=0, cache_scope="public")

    async with _asgi_client(Server("test", on_list_tools=list_tools), json_response=False) as http:
        with anyio.fail_after(5):
            response = await http.post("/mcp", json=_list_tools_body(), headers={MCP_METHOD_HEADER: "tools/list"})

    assert response.status_code == 200
    assert response.headers["content-type"].split(";", 1)[0] == "text/event-stream"
    assert response.content.count(b": ping\r\n\r\n") == 2
    events = _sse_payloads(response.text)
    assert len(events) == 1
    assert events[0]["result"]["tools"] == []


async def test_sse_mode_streams_log_notification() -> None:
    """SDK-defined: notifications on the request's outbound channel reach the per-request SSE stream."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        await ctx.session.send_notification(
            LoggingMessageNotification(params=LoggingMessageNotificationParams(level="info", data="hello")),
            related_request_id=ctx.request_id,
        )
        return ListToolsResult(tools=[], ttl_ms=0, cache_scope="public")

    async with _asgi_client(Server("test", on_list_tools=list_tools), json_response=False) as http:
        with anyio.fail_after(5):
            response = await http.post("/mcp", json=_list_tools_body(), headers={MCP_METHOD_HEADER: "tools/list"})

    assert response.headers["content-type"].split(";", 1)[0] == "text/event-stream"
    events = _sse_payloads(response.text)
    assert len(events) == 2
    assert events[0]["method"] == "notifications/message"
    assert events[0]["params"] == {"level": "info", "data": "hello"}
    assert events[1]["result"]["tools"] == []


async def test_json_mode_drops_progress() -> None:
    """SDK-defined: `report_progress` has no sink in JSON mode; only the terminal result ships."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        await ctx.session.report_progress(1, total=2)
        return ListToolsResult(tools=[], ttl_ms=0, cache_scope="public")

    async with _asgi_client(Server("test", on_list_tools=list_tools), json_response=True) as http:
        response = await http.post(
            "/mcp", json=_list_tools_body_with_token("tok"), headers={MCP_METHOD_HEADER: "tools/list"}
        )

    assert response.headers["content-type"].split(";", 1)[0] == "application/json"
    body = response.json()
    assert body["id"] == 1
    assert body["result"]["tools"] == []
    assert "notifications/progress" not in response.text


async def test_sse_mode_error_before_any_notify_is_json_with_mapped_status() -> None:
    """Spec-mandated: METHOD_NOT_FOUND maps to HTTP 404; SSE has not committed, so the error is plain JSON."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        raise MCPError(code=METHOD_NOT_FOUND, message="nope")

    async with _asgi_client(Server("test", on_list_tools=list_tools), json_response=False) as http:
        with anyio.fail_after(5):
            response = await http.post("/mcp", json=_list_tools_body(), headers={MCP_METHOD_HEADER: "tools/list"})

    assert response.status_code == 404
    assert response.headers["content-type"].split(";", 1)[0] == "application/json"
    assert response.json() == {"jsonrpc": "2.0", "id": 1, "error": {"code": METHOD_NOT_FOUND, "message": "nope"}}


async def test_sse_mode_error_after_notify_is_sse_event() -> None:
    """Headers committed on the first notification, so the error ships as the terminal SSE event at 200."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        await ctx.session.report_progress(1.0)
        raise MCPError(code=INTERNAL_ERROR, message="boom")

    async with _asgi_client(Server("test", on_list_tools=list_tools), json_response=False) as http:
        with anyio.fail_after(5):
            response = await http.post(
                "/mcp", json=_list_tools_body_with_token("tok"), headers={MCP_METHOD_HEADER: "tools/list"}
            )

    assert response.status_code == 200
    assert response.headers["content-type"].split(";", 1)[0] == "text/event-stream"
    events = _sse_payloads(response.text)
    assert len(events) == 2
    assert events[0]["method"] == "notifications/progress"
    assert events[1] == {"jsonrpc": "2.0", "id": 1, "error": {"code": INTERNAL_ERROR, "message": "boom"}}


async def test_sse_mode_no_notify_response_is_json() -> None:
    """SDK-defined: no progressToken makes `report_progress` a no-op, so nothing streams and SSE never commits."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        await ctx.session.report_progress(1, total=2)
        return ListToolsResult(tools=[], ttl_ms=0, cache_scope="public")

    async with _asgi_client(Server("test", on_list_tools=list_tools), json_response=False) as http:
        with anyio.fail_after(5):
            response = await http.post("/mcp", json=_list_tools_body(), headers={MCP_METHOD_HEADER: "tools/list"})

    assert response.status_code == 200
    assert response.headers["content-type"].split(";", 1)[0] == "application/json"
    assert response.json()["result"]["tools"] == []


async def test_accept_missing_sse_406_in_sse_mode() -> None:
    """SDK-defined: SSE mode requires accepting both representations; rejected before JSON-RPC parsing."""
    async with _asgi_client(Server("test"), json_response=False, accept="application/json") as http:
        response = await http.post("/mcp", json=_list_tools_body(), headers={MCP_METHOD_HEADER: "tools/list"})
    assert response.status_code == 406
    assert response.content == b""


async def test_accept_missing_sse_ok_in_json_mode() -> None:
    """SDK-defined: JSON mode only needs `application/json` to be acceptable."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[], ttl_ms=0, cache_scope="public")

    async with _asgi_client(
        Server("test", on_list_tools=list_tools), json_response=True, accept="application/json"
    ) as http:
        response = await http.post("/mcp", json=_list_tools_body(), headers={MCP_METHOD_HEADER: "tools/list"})
    assert response.status_code == 200
    assert response.headers["content-type"].split(";", 1)[0] == "application/json"


@pytest.mark.parametrize("json_response", [True, False])
async def test_accept_wildcard_satisfies_both_response_modes(json_response: bool) -> None:
    """SDK-defined: the RFC 7231 wildcard satisfies both representations."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[], ttl_ms=0, cache_scope="public")

    async with _asgi_client(
        Server("test", on_list_tools=list_tools), json_response=json_response, accept="*/*"
    ) as http:
        with anyio.fail_after(5):
            response = await http.post("/mcp", json=_list_tools_body(), headers={MCP_METHOD_HEADER: "tools/list"})
    assert response.status_code == 200


async def test_late_notify_after_terminal_dropped() -> None:
    """SDK-defined: a closed sink must not surface as an exception from the dispatch context."""
    send_ch, recv_ch = anyio.create_memory_object_stream[bytes](0)
    dctx = _SingleExchangeDispatchContext(
        transport=TransportContext(kind="streamable-http", can_send_request=False),
        request_id=1,
        message_metadata=None,
        sink=send_ch,
    )
    await recv_ch.aclose()
    # Neither raises despite the receiver being gone (BrokenResourceError caught and dropped).
    assert await dctx.notify("notifications/message", {"level": "info", "data": "late"}) is None
    dctx.progress_token = "tok"
    assert await dctx.progress(1.0) is None
    await send_ch.aclose()


async def test_disconnect_cancels_handler_and_runs_exit_stack() -> None:
    """SDK-defined: `serve_one`'s shielded cleanup runs on the disconnect-cancellation path, so
    handler-registered teardown is not skipped."""
    handler_started = anyio.Event()
    cleanup_ran = anyio.Event()

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        ctx.session._connection.exit_stack.callback(cleanup_ran.set)
        handler_started.set()
        await anyio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover

    server: Server[Any] = Server("test", on_list_tools=list_tools)
    body = json.dumps(_list_tools_body()).encode()
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 1234),
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"accept", b"application/json, text/event-stream"),
            (MCP_PROTOCOL_VERSION_HEADER.encode(), LATEST_MODERN_VERSION.encode()),
            (MCP_METHOD_HEADER.encode(), b"tools/list"),
        ],
    }
    request_delivered = anyio.Event()

    async def receive() -> Message:
        # First call delivers the request body; once the handler is parked, deliver disconnect.
        if not request_delivered.is_set():
            request_delivered.set()
            return {"type": "http.request", "body": body, "more_body": False}
        await handler_started.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:  # pragma: no cover
        pass

    with anyio.fail_after(5):
        async with server.lifespan(server) as lifespan_state:
            await handle_modern_request(server, None, False, lifespan_state, scope, receive, send)
        await cleanup_ran.wait()

    assert handler_started.is_set()
