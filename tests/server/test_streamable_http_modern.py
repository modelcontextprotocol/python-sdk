"""Unit tests for the 2026-07-28 single-exchange HTTP serving entry.

The interaction suite under ``tests/interaction/transports/test_hosting_http_modern.py`` pins
the wire contract end to end; these tests cover the module's internal seams directly --
the closed back-channel on the dispatch context, and the request-validation ladder in
``handle_modern_request``.
"""

import logging
from typing import Any

import anyio
import httpx
import pytest
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
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
    PaginatedRequestParams,
    Tool,
)
from mcp_types.version import LATEST_MODERN_VERSION
from starlette.types import Receive, Scope, Send

from mcp.server import Server, ServerRequestContext, runner
from mcp.server._streamable_http_modern import (
    _SingleExchangeDispatchContext,
    _to_jsonrpc_response,
    handle_modern_request,
)
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError, NoBackChannelError
from mcp.shared.inbound import MCP_PROTOCOL_VERSION_HEADER
from mcp.shared.transport_context import TransportContext

pytestmark = pytest.mark.anyio


async def test_single_exchange_dispatch_context_has_no_back_channel() -> None:
    """The per-request dispatch context refuses server-initiated requests and drops notify/progress."""
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


def _asgi_client(server: Server[Any], security_settings: TransportSecuritySettings | None = None) -> httpx.AsyncClient:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        async with server.lifespan(server) as lifespan_state:
            await handle_modern_request(server, security_settings, lifespan_state, scope, receive, send)

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={MCP_PROTOCOL_VERSION_HEADER: LATEST_MODERN_VERSION},
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
        response = await http.post("/mcp", json=body, headers={"content-type": "application/json"})
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
            response = await http.post("/mcp", json=_list_tools_body(), headers={"content-type": "application/json"})

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
            response = await http.post("/mcp", json=_list_tools_body(), headers={"content-type": "application/json"})
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
