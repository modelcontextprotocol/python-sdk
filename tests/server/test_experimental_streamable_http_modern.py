"""Unit tests for the experimental 2026-07-28 single-exchange HTTP serving entry.

The interaction suite under ``tests/interaction/transports/test_hosting_http_modern.py`` pins
the wire contract end to end; these tests cover the module's internal seams directly --
the closed back-channel on the dispatcher and dispatch context, the exception-to-error
mapping in ``handle()``, and the request-validation ladder in ``handle_modern_request``.
"""

import logging
from collections.abc import Mapping
from typing import Any

import anyio
import httpx
import pytest
from starlette.requests import Request
from starlette.types import Receive, Scope, Send

import mcp.server._experimental.streamable_http_modern as modern
from mcp.server import Server, ServerRequestContext
from mcp.server._experimental.streamable_http_modern import (
    SingleExchangeDispatcher,
    _SingleExchangeDispatchContext,
    handle_modern_request,
)
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.dispatcher import DispatchContext
from mcp.shared.exceptions import NoBackChannelError
from mcp.shared.transport_context import TransportContext
from mcp.types import INVALID_PARAMS, PARSE_ERROR, JSONRPCError, JSONRPCRequest, ListToolsResult, PaginatedRequestParams

pytestmark = pytest.mark.anyio


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "headers": []})


async def test_single_exchange_dispatcher_has_no_back_channel_and_is_never_driven() -> None:
    """The dispatcher refuses server-initiated requests, drops notifications, and is not run-driven.

    A 2026-07-28 POST has no channel for the server to push to the client, and ``ServerRunner``
    never calls ``run()`` on this dispatcher -- ``handle()`` is invoked directly per request.
    """
    dispatcher = SingleExchangeDispatcher(_request())
    with pytest.raises(NoBackChannelError):
        await dispatcher.send_raw_request("sampling/createMessage", None)
    assert await dispatcher.notify("notifications/message", None) is None

    async def on_request(ctx: DispatchContext[Any], method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        raise AssertionError("unreachable")  # pragma: no cover

    async def on_notify(ctx: DispatchContext[Any], method: str, params: Mapping[str, Any] | None) -> None:
        raise AssertionError("unreachable")  # pragma: no cover

    with pytest.raises(RuntimeError, match="never driven"):
        await dispatcher.run(on_request, on_notify)


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


async def test_handle_maps_validation_error_to_invalid_params() -> None:
    """A handler raising ``ValidationError`` is mapped to a ``-32602`` JSON-RPC error.

    Mirrors ``JSONRPCDispatcher``'s exception-to-wire boundary: a Pydantic validation failure
    inside the handler becomes ``INVALID_PARAMS`` rather than the generic internal error.
    """

    async def on_request(ctx: DispatchContext[Any], method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        JSONRPCRequest.model_validate({})  # raises ValidationError
        raise AssertionError("unreachable")  # pragma: no cover

    dispatcher = SingleExchangeDispatcher(_request())
    msg = await dispatcher.handle(JSONRPCRequest(jsonrpc="2.0", id=7, method="tools/call", params={}), on_request)
    assert isinstance(msg, JSONRPCError)
    assert msg.id == 7
    assert msg.error.code == INVALID_PARAMS


def _asgi_client(server: Server[Any], security_settings: TransportSecuritySettings | None = None) -> httpx.AsyncClient:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await handle_modern_request(server, security_settings, scope, receive, send)

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


async def test_handle_modern_request_rejects_non_post_with_405() -> None:
    """A GET on the 2026-07-28 entry is answered with 405 before any body is read."""
    async with _asgi_client(Server("test")) as http:
        response = await http.get("/mcp")
    assert response.status_code == 405
    assert response.headers["allow"] == "POST"


async def test_handle_modern_request_rejects_malformed_body_with_parse_error() -> None:
    """A POST whose body is not a valid ``JSONRPCRequest`` returns 400 with ``-32700``."""
    async with _asgi_client(Server("test")) as http:
        response = await http.post("/mcp", content=b"not json", headers={"content-type": "application/json"})
    assert response.status_code == 400
    assert response.headers["content-type"].split(";", 1)[0] == "application/json"
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": PARSE_ERROR, "message": "Parse error", "data": None},
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
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientInfo": {"name": "raw", "version": "0.0.0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta}}


async def test_handle_modern_request_sends_response_when_exit_stack_cleanup_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A raising ``connection.exit_stack`` callback is logged and swallowed; the computed result still ships.

    The exit-stack guard mirrors ``ServerRunner.run``: cleanup runs in a ``finally`` after the
    handler, and an exception there must not displace the JSON-RPC response that was already built.
    """

    async def boom() -> None:
        raise RuntimeError("cleanup failed")

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        ctx.session._connection.exit_stack.push_async_callback(boom)
        return ListToolsResult(tools=[], ttl_ms=0, cache_scope="public")

    with caplog.at_level(logging.ERROR, logger=modern.__name__):
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
    monkeypatch.setattr(modern, "_EXIT_STACK_CLOSE_TIMEOUT", 0)

    async def block() -> None:
        await anyio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover

    async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        ctx.session._connection.exit_stack.push_async_callback(block)
        return ListToolsResult(tools=[], ttl_ms=0, cache_scope="public")

    with anyio.fail_after(5), caplog.at_level(logging.WARNING, logger=modern.__name__):
        async with _asgi_client(Server("test", on_list_tools=list_tools)) as http:
            response = await http.post("/mcp", json=_list_tools_body(), headers={"content-type": "application/json"})
    # coverage.py on Python 3.11 misreports the lines below as unhit (the test passes there);
    # the shielded-cancel path inside the request task disrupts the tracer in this frame.
    assert response.status_code == 200  # pragma: lax no cover
    assert response.json()["result"]["tools"] == []  # pragma: lax no cover
    assert "abandoning remaining callbacks" in caplog.text  # pragma: lax no cover
