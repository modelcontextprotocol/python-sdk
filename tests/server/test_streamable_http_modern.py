"""Unit tests for the 2026-07-28 single-exchange HTTP serving entry.

The interaction suite under ``tests/interaction/transports/test_hosting_http_modern.py`` pins
the wire contract end to end; these tests cover the module's internal seams directly --
the closed back-channel on the dispatch context, and the request-validation ladder in
``handle_modern_request``.
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
    """The per-request dispatch context refuses server-initiated requests; without an SSE sink,
    notify/progress are no-ops."""
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
    """SDK-defined: a GET on the modern entry is an HTTP-verb mismatch — 405 Method Not
    Allowed with ``Allow: POST`` per RFC 9110. This is HTTP-layer (before JSON-RPC parsing)
    so there is no JSON-RPC body."""
    async with _asgi_client(Server("test")) as http:
        response = await http.get("/mcp")
    assert response.status_code == 405
    assert response.headers["allow"] == "POST"
    assert response.content == b""


async def test_handle_modern_request_rejects_a_notification_body_with_invalid_request() -> None:
    """SDK-defined: well-formed JSON that isn't a single JSON-RPC request object (e.g. a
    notification, which lacks ``id``) is ``INVALID_REQUEST`` — distinct from ``PARSE_ERROR``,
    which is for malformed JSON."""
    async with _asgi_client(Server("test")) as http:
        response = await http.post(
            "/mcp",
            content=b'{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":1}}',
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == INVALID_REQUEST


async def test_handle_modern_request_rejects_malformed_body_with_parse_error() -> None:
    """An unparseable POST body yields HTTP 400 with a ``PARSE_ERROR`` JSON-RPC error envelope.

    SDK-defined: the 400 status comes from the SDK's error-code→HTTP-status table; spec-mandated: the
    body is a full JSON-RPC error object with ``id: null`` and code ``-32700``.
    """
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
    """The transport-security middleware's error response is sent verbatim and short-circuits."""
    settings = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["good.example"])
    async with _asgi_client(Server("test"), security_settings=settings) as http:
        response = await http.post("/mcp", json={}, headers={"content-type": "application/json"})
    assert response.status_code == 421
    assert response.text == "Invalid Host header"


def _list_tools_body() -> dict[str, Any]:
    """A minimal valid 2026-07-28 ``tools/list`` request body, including the required ``_meta`` envelope."""
    meta = {
        PROTOCOL_VERSION_META_KEY: LATEST_MODERN_VERSION,
        CLIENT_INFO_META_KEY: {"name": "raw", "version": "0.0.0"},
        CLIENT_CAPABILITIES_META_KEY: {},
    }
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta}}


async def test_handle_modern_request_routes_with_mis_shaped_envelope_client_info() -> None:
    """SDK-defined: a mis-shaped ``clientInfo`` envelope value is treated as not supplied —
    the request still routes (200 + result) and the handler observes ``client_params is None``
    rather than the request being rejected at the validation ladder. A non-spec method is
    used so the kernel's per-method params validation does not re-reject the envelope."""
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
    """A raising ``connection.exit_stack`` callback is logged and swallowed; the computed result still ships.

    The exit-stack guard is `aclose_shielded`: cleanup runs in `serve_one`'s ``finally`` after
    the handler, and an exception there must not displace the JSON-RPC response that was already
    built.
    """

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
    """A blocking ``connection.exit_stack`` callback is abandoned at the grace deadline; the response still ships.

    Grace patched to 0 so the deadline is already expired on entry: the bounded unwind cancels the
    blocker at its first checkpoint, the abandonment warning is logged, and the JSON-RPC response
    that was built before cleanup is sent unchanged.
    """
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
    # coverage.py on Python 3.11 misreports the lines below as unhit (the test passes there);
    # the shielded-cancel path inside the request task disrupts the tracer in this frame.
    assert response.status_code == 200  # pragma: lax no cover
    assert response.json()["result"]["tools"] == []  # pragma: lax no cover
    assert "abandoning remaining callbacks" in caplog.text  # pragma: lax no cover


# --- _to_jsonrpc_response ------------------------------------------------------


async def test_to_jsonrpc_response_wraps_success_as_jsonrpc_response() -> None:
    """SDK-defined: a handler coroutine resolving to a result dict is wrapped as a
    `JSONRPCResponse` carrying the supplied id and the dict verbatim as `result`."""

    async def ok() -> dict[str, Any]:
        return {"k": "v"}

    reply = await _to_jsonrpc_response(7, ok())
    assert isinstance(reply, JSONRPCResponse)
    assert reply.id == 7
    assert reply.result == {"k": "v"}


async def test_to_jsonrpc_response_maps_mcp_error_to_jsonrpc_error() -> None:
    """SDK-defined: an `MCPError` raised by the handler coroutine is wrapped as a
    `JSONRPCError` whose `error` carries the same code, message, and data."""

    async def fail() -> dict[str, Any]:
        raise MCPError(code=METHOD_NOT_FOUND, message="nope", data="x")

    reply = await _to_jsonrpc_response("rid", fail())
    assert isinstance(reply, JSONRPCError)
    assert reply.id == "rid"
    assert reply.error == ErrorData(code=METHOD_NOT_FOUND, message="nope", data="x")


async def test_to_jsonrpc_response_maps_validation_error_to_invalid_params() -> None:
    """SDK-defined: a pydantic `ValidationError` escaping the handler coroutine is
    mapped to `INVALID_PARAMS` with a generic message (validator detail does not
    reach the wire)."""

    async def fail() -> dict[str, Any]:
        Tool.model_validate({"name": 123})  # raises ValidationError
        raise NotImplementedError

    reply = await _to_jsonrpc_response(1, fail())
    assert isinstance(reply, JSONRPCError)
    assert reply.error == ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data="")


async def test_to_jsonrpc_response_maps_unmapped_exception_to_internal_error_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SDK-defined: an unmapped exception is logged server-side and surfaced as
    `INTERNAL_ERROR` with a generic message; the exception text never reaches the
    wire."""

    async def fail() -> dict[str, Any]:
        raise RuntimeError("boom")

    reply = await _to_jsonrpc_response(1, fail())
    assert isinstance(reply, JSONRPCError)
    assert reply.error.code == INTERNAL_ERROR
    # Handler internals never reach the wire.
    assert "boom" not in reply.error.message
    assert "request handler raised" in caplog.text


# --- header cross-check at the wire --------------------------------------------


async def test_handle_modern_request_rejects_mismatched_method_header_with_400_and_header_mismatch() -> None:
    """Spec-mandated: an `Mcp-Method` header that disagrees with `body.method` is rejected at the
    boundary as HTTP 400 with JSON-RPC error code HEADER_MISMATCH; the handler never runs."""
    async with _asgi_client(Server("test")) as http:
        response = await http.post("/mcp", json=_list_tools_body(), headers={MCP_METHOD_HEADER: "prompts/list"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == HEADER_MISMATCH


async def test_handle_modern_request_rejects_mismatched_name_header_with_400_and_header_mismatch() -> None:
    """Spec-mandated: for a name-bearing method, an `Mcp-Name` header that disagrees with the body's
    named param is rejected as HTTP 400 with JSON-RPC error code HEADER_MISMATCH."""
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


# --- SSE response mode ---------------------------------------------------------


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
    """SSE mode: a handler's `report_progress` calls stream as `notifications/progress` events
    (carrying the request's progressToken) before the terminal JSON-RPC response event.

    Spec-mandated: `notifications/progress` carries the caller's token; the per-request SSE stream
    closes after the terminal response. Asserted at the wire because Content-Type and event order
    are the contract.
    """

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
    """SSE mode: while the stream is idle between events the server emits an SSE comment line so a
    proxy idle-read timeout does not close the stream (which would cancel the handler).
    SDK-defined: spec encourages keepalive comments for long-lived streams.

    Runs on trio's autojumping MockClock so the `move_on_after(_SSE_PING_INTERVAL)` deadlines and
    the handler's `anyio.sleep` advance without wall-clock time."""
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
    """SSE mode: a handler that runs silent past the deferral window commits `text/event-stream`
    and starts pinging — even though it never emits a notification — so a proxy idle-read timeout
    does not close the connection and cancel it. SDK-defined: the deferral window is bounded by
    `_SSE_PING_INTERVAL`.

    Runs on trio's autojumping MockClock; the 2.5s handler sleep takes no wall-clock time."""
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
    """SSE mode: a request-scoped `notifications/message` emitted by the handler precedes the
    terminal response on the same stream. SDK-defined: notifications sent on the request's outbound
    channel reach the per-request SSE response."""

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
    """JSON mode: `report_progress` is a no-op (no sink); the response is a plain
    `application/json` body carrying only the terminal result. SDK-defined."""

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
    """SSE mode: an error raised before the handler emits any notification is written as
    `application/json` with the table-mapped HTTP status — SSE has not committed yet.
    Spec-mandated: METHOD_NOT_FOUND MUST be `404 Not Found`."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        raise MCPError(code=METHOD_NOT_FOUND, message="nope")

    async with _asgi_client(Server("test", on_list_tools=list_tools), json_response=False) as http:
        with anyio.fail_after(5):
            response = await http.post("/mcp", json=_list_tools_body(), headers={MCP_METHOD_HEADER: "tools/list"})

    assert response.status_code == 404
    assert response.headers["content-type"].split(";", 1)[0] == "application/json"
    assert response.json() == {"jsonrpc": "2.0", "id": 1, "error": {"code": METHOD_NOT_FOUND, "message": "nope"}}


async def test_sse_mode_error_after_notify_is_sse_event() -> None:
    """SSE mode: an error raised after the handler has emitted is delivered as the terminal SSE
    event (HTTP 200) — `text/event-stream` headers were committed on the first notification."""

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
    """SSE mode: a handler that emits nothing (here `report_progress` is a no-op because no
    `progressToken` was supplied) gets a plain `application/json` response. SDK-defined: SSE only
    commits once there is something to stream."""

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
    """SDK-defined: in SSE mode the client must accept both `application/json` and
    `text/event-stream`; an Accept header naming only JSON is rejected at HTTP 406 before any
    JSON-RPC parsing."""
    async with _asgi_client(Server("test"), json_response=False, accept="application/json") as http:
        response = await http.post("/mcp", json=_list_tools_body(), headers={MCP_METHOD_HEADER: "tools/list"})
    assert response.status_code == 406
    assert response.content == b""


async def test_accept_missing_sse_ok_in_json_mode() -> None:
    """SDK-defined: in JSON mode only `application/json` need be acceptable; an Accept header that
    omits `text/event-stream` still routes (200 + result)."""

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
    """SDK-defined: `Accept: */*` satisfies both representations (RFC 7231 wildcard) in either
    response mode."""

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[], ttl_ms=0, cache_scope="public")

    async with _asgi_client(
        Server("test", on_list_tools=list_tools), json_response=json_response, accept="*/*"
    ) as http:
        with anyio.fail_after(5):
            response = await http.post("/mcp", json=_list_tools_body(), headers={MCP_METHOD_HEADER: "tools/list"})
    assert response.status_code == 200


async def test_late_notify_after_terminal_dropped() -> None:
    """SDK-defined: a `notify()` after the SSE sink has closed is silently dropped — the closed
    stream must not propagate as an exception out of the dispatch context."""
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
    """SSE mode: when the client disconnects mid-stream the handler task is cancelled and
    `connection.exit_stack` still unwinds. SDK-defined: `serve_one`'s shielded cleanup runs in the
    cancellation path so handler-registered teardown is not skipped on disconnect."""
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
