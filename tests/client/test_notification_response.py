"""Tests for StreamableHTTP client transport with non-SDK servers.

These tests verify client behavior when interacting with servers
that don't follow SDK conventions.
"""

import json

import anyio
import httpx2
import mcp_types as types
import pytest
from mcp_types import RootsListChangedNotification
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from mcp import ClientSession, MCPError
from mcp.client import IncomingMessage
from mcp.client._transport import SESSION_EXPIRED, SESSION_EXPIRED_MARKER
from mcp.client.streamable_http import streamable_http_client

pytestmark = pytest.mark.anyio

INIT_RESPONSE = {
    "serverInfo": {"name": "test-non-sdk-server", "version": "1.0.0"},
    "protocolVersion": "2024-11-05",
    "capabilities": {},
}


def _init_json_response(data: dict[str, object]) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": data["id"], "result": INIT_RESPONSE})


def _create_non_sdk_server_app() -> Starlette:
    """Create a minimal server that doesn't follow SDK conventions."""

    async def handle_mcp_request(request: Request) -> Response:
        body = await request.body()
        data = json.loads(body)

        if data.get("method") == "initialize":
            return _init_json_response(data)

        # For notifications, return 204 No Content (non-SDK behavior)
        if "id" not in data:
            return Response(status_code=204, headers={"Content-Type": "application/json"})

        return JSONResponse(  # pragma: no cover
            {"jsonrpc": "2.0", "id": data.get("id"), "error": {"code": -32601, "message": "Method not found"}}
        )

    return Starlette(debug=True, routes=[Route("/mcp", handle_mcp_request, methods=["POST"])])


def _create_unexpected_content_type_app() -> Starlette:
    """Create a server that returns an unexpected content type for requests."""

    async def handle_mcp_request(request: Request) -> Response:
        body = await request.body()
        data = json.loads(body)

        if data.get("method") == "initialize":
            return _init_json_response(data)

        if "id" not in data:
            return Response(status_code=202)

        # Return text/plain for all other requests — an unexpected content type.
        return Response(content="this is plain text, not json or sse", status_code=200, media_type="text/plain")

    return Starlette(debug=True, routes=[Route("/mcp", handle_mcp_request, methods=["POST"])])


async def test_non_compliant_notification_response() -> None:
    """Verify the client ignores unexpected responses to notifications.

    The spec states notifications should get either 202 + no response body, or 4xx + optional error body
    (https://modelcontextprotocol.io/specification/2025-06-18/basic/transports#sending-messages-to-the-server),
    but some servers wrongly return other 2xx codes (e.g. 204). For now we simply ignore unexpected responses
    (aligning behaviour w/ the TS SDK).
    """
    returned_exception = None

    async def message_handler(message: IncomingMessage) -> None:  # pragma: no cover
        nonlocal returned_exception
        if isinstance(message, Exception):
            returned_exception = message

    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=_create_non_sdk_server_app())) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream, message_handler=message_handler) as session:
                await session.initialize()

                # The test server returns a 204 instead of the expected 202
                await session.send_notification(RootsListChangedNotification(method="notifications/roots/list_changed"))

    if returned_exception:  # pragma: no cover
        pytest.fail(f"Server encountered an exception: {returned_exception}")


async def test_unexpected_content_type_sends_jsonrpc_error() -> None:
    """Verify unexpected content types unblock the pending request with an MCPError.

    When a server returns a content type that is neither application/json nor text/event-stream,
    the client should send a JSONRPCError so the pending request resolves immediately
    instead of hanging until timeout.
    """
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=_create_unexpected_content_type_app())) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()

                with pytest.raises(MCPError, match="Unexpected content type: text/plain"):  # pragma: no branch
                    await session.list_tools()


def _create_http_error_app(error_status: int, *, error_on_notifications: bool = False) -> Starlette:
    """Create a server that returns an HTTP error for non-init requests."""

    async def handle_mcp_request(request: Request) -> Response:
        body = await request.body()
        data = json.loads(body)

        if data.get("method") == "initialize":
            return _init_json_response(data)

        if "id" not in data:
            if error_on_notifications:
                return Response(status_code=error_status)
            return Response(status_code=202)

        return Response(status_code=error_status)

    return Starlette(debug=True, routes=[Route("/mcp", handle_mcp_request, methods=["POST"])])


async def test_http_error_status_sends_jsonrpc_error() -> None:
    """Verify HTTP 5xx errors unblock the pending request with an MCPError.

    When a server returns a non-2xx status code (e.g. 500), the client should
    send a JSONRPCError so the pending request resolves immediately instead of
    raising an unhandled httpx2.HTTPStatusError that causes the caller to hang.
    """
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=_create_http_error_app(500))) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()

                with pytest.raises(MCPError, match="Server returned an error response"):  # pragma: no branch
                    await session.list_tools()


async def test_http_error_on_notification_does_not_hang() -> None:
    """Verify HTTP errors on notifications are silently ignored.

    When a notification gets an HTTP error, there is no pending request to
    unblock, so the client should just return without sending a JSONRPCError.
    """
    app = _create_http_error_app(500, error_on_notifications=True)
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()

                # Should not raise or hang — the error is silently ignored for notifications
                await session.send_notification(RootsListChangedNotification(method="notifications/roots/list_changed"))


def _create_invalid_json_response_app() -> Starlette:
    """Create a server that returns invalid JSON for requests."""

    async def handle_mcp_request(request: Request) -> Response:
        body = await request.body()
        data = json.loads(body)

        if data.get("method") == "initialize":
            return _init_json_response(data)

        if "id" not in data:
            return Response(status_code=202)

        # Return application/json content type but with invalid JSON body.
        return Response(content="not valid json{{{", status_code=200, media_type="application/json")

    return Starlette(debug=True, routes=[Route("/mcp", handle_mcp_request, methods=["POST"])])


async def test_invalid_json_response_sends_jsonrpc_error() -> None:
    """Verify invalid JSON responses unblock the pending request with an MCPError.

    When a server returns application/json with an unparseable body, the client
    should send a JSONRPCError so the pending request resolves immediately
    instead of hanging until timeout.
    """
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=_create_invalid_json_response_app())) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()

                with pytest.raises(MCPError, match="Failed to parse JSON response"):  # pragma: no branch
                    await session.list_tools()


def _create_non_2xx_json_body_app(status: int, body: bytes) -> Starlette:
    """Server that returns a fixed non-2xx status + ``application/json`` body for non-init requests.

    The initialize response carries an ``mcp-session-id`` so the client treats subsequent
    requests as part of an established session (needed for the 404 → session-terminated mapping).
    """

    async def handle_mcp_request(request: Request) -> Response:
        data = json.loads(await request.body())
        if data.get("method") == "initialize":
            return JSONResponse(
                {"jsonrpc": "2.0", "id": data["id"], "result": INIT_RESPONSE},
                headers={"mcp-session-id": "test-session"},
            )
        if "id" not in data:
            return Response(status_code=202)
        return Response(content=body, status_code=status, media_type="application/json")

    return Starlette(debug=True, routes=[Route("/mcp", handle_mcp_request, methods=["POST"])])


async def test_client_surfaces_jsonrpc_error_from_non_2xx_body_with_correlated_id() -> None:
    """SDK-defined: a JSON-RPC error in a non-2xx body is surfaced verbatim even when the
    server set ``id: null`` — the client rewraps it under the pending request's id, so
    the awaiting call resolves with the server's error code instead of the generic fallback."""
    body = json.dumps(
        {"jsonrpc": "2.0", "id": None, "error": {"code": types.METHOD_NOT_FOUND, "message": "nope"}}
    ).encode()
    app = _create_non_2xx_json_body_app(400, body)
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()
                with pytest.raises(MCPError) as exc:
                    await session.list_tools()
                assert exc.value.error.code == types.METHOD_NOT_FOUND


async def test_client_falls_back_to_generic_error_when_non_2xx_body_is_a_jsonrpc_result() -> None:
    """SDK-defined: a non-2xx response whose JSON body parses as a JSON-RPC *result* (not an
    error) falls through to the generic ``INTERNAL_ERROR`` fallback rather than being
    treated as the request's reply."""
    app = _create_non_2xx_json_body_app(400, b'{"jsonrpc":"2.0","id":1,"result":{}}')
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()
                with pytest.raises(MCPError) as exc:
                    await session.list_tools()
                assert exc.value.error.code == types.INTERNAL_ERROR


async def test_client_reports_session_expiry_after_a_404_recovery_retry_has_malformed_json() -> None:
    """SDK-defined: a malformed 404 body still triggers one session recovery attempt before failing.

    The parse failure is not surfaced because HTTP 404 is the transport's session-expiry signal. A second
    404 after recovery is bounded and returns the private session-expired error rather than looping.
    """
    app = _create_non_2xx_json_body_app(404, b"not valid json{{{")
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()
                with pytest.raises(MCPError) as exc:
                    await session.list_tools()
                assert exc.value.error.code == SESSION_EXPIRED


def _create_expired_session_recovery_app(requests: list[tuple[str, str | None]]) -> Starlette:
    """Return a fresh session after rejecting one established-session request."""
    initialize_count = 0
    expire_once = True

    async def handle_mcp_request(request: Request) -> Response:
        nonlocal expire_once, initialize_count
        data = json.loads(await request.body())
        method = data.get("method")
        session_id = request.headers.get("mcp-session-id")
        requests.append((method, session_id))

        if method == "initialize":
            initialize_count += 1
            return JSONResponse(
                {"jsonrpc": "2.0", "id": data["id"], "result": INIT_RESPONSE},
                headers={"mcp-session-id": f"session-{initialize_count}"},
            )
        if method == "notifications/initialized":
            return Response(status_code=202)
        if method == "tools/list" and expire_once:
            expire_once = False
            assert session_id == "session-1"
            return Response(status_code=404)
        if method == "tools/list":
            assert session_id == "session-2"
            return JSONResponse({"jsonrpc": "2.0", "id": data["id"], "result": {"tools": []}})
        return Response(status_code=500)

    return Starlette(debug=True, routes=[Route("/mcp", handle_mcp_request, methods=["POST"])])


async def test_client_reinitializes_once_after_an_established_session_returns_404() -> None:
    """Spec-mandated: a 404 for an established legacy session creates a fresh session and retries once.

    The recovery initialize must omit the expired session id; its initialized notification and the retried
    request must carry the new id. This drives the public ``ClientSession`` API through an in-process ASGI app.
    """
    requests: list[tuple[str, str | None]] = []
    app = _create_expired_session_recovery_app(requests)

    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                result = await session.initialize()
                assert result.server_info.name == "test-non-sdk-server"

                tools = await session.list_tools()

    assert tools.tools == []
    assert requests == [
        ("initialize", None),
        ("notifications/initialized", "session-1"),
        ("tools/list", "session-1"),
        ("initialize", None),
        ("notifications/initialized", "session-2"),
        ("tools/list", "session-2"),
    ]


def _create_repeated_expired_session_app(requests: list[tuple[str, str | None]]) -> Starlette:
    """Always expire requests from an established session."""
    initialize_count = 0

    async def handle_mcp_request(request: Request) -> Response:
        nonlocal initialize_count
        data = json.loads(await request.body())
        method = data.get("method")
        session_id = request.headers.get("mcp-session-id")
        requests.append((method, session_id))

        if method == "initialize":
            initialize_count += 1
            return JSONResponse(
                {"jsonrpc": "2.0", "id": data["id"], "result": INIT_RESPONSE},
                headers={"mcp-session-id": f"session-{initialize_count}"},
            )
        if method == "notifications/initialized":
            return Response(status_code=202)
        if method == "tools/list":
            return Response(status_code=404)
        return Response(status_code=500)

    return Starlette(debug=True, routes=[Route("/mcp", handle_mcp_request, methods=["POST"])])


async def test_client_retries_an_expired_session_request_only_once() -> None:
    """SDK-defined: a retry that also receives 404 surfaces an error instead of opening a recovery loop."""
    requests: list[tuple[str, str | None]] = []
    app = _create_repeated_expired_session_app(requests)

    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                with pytest.raises(MCPError) as exc_info:
                    await session.list_tools()

    assert exc_info.value.code == SESSION_EXPIRED
    assert exc_info.value.data == {SESSION_EXPIRED_MARKER: True}
    assert requests == [
        ("initialize", None),
        ("notifications/initialized", "session-1"),
        ("tools/list", "session-1"),
        ("initialize", None),
        ("notifications/initialized", "session-2"),
        ("tools/list", "session-2"),
    ]


async def test_concurrent_expired_session_requests_share_one_reinitialization() -> None:
    """SDK-defined: concurrent 404 responses recover one session generation, not one per caller."""
    requests: list[tuple[str, str | None]] = []
    old_requests_started = 0
    old_requests_ready = anyio.Event()
    release_old_requests = anyio.Event()
    initialize_count = 0

    async def handle_mcp_request(request: Request) -> Response:
        nonlocal initialize_count, old_requests_started
        data = json.loads(await request.body())
        method = data.get("method")
        session_id = request.headers.get("mcp-session-id")
        requests.append((method, session_id))

        if method == "initialize":
            initialize_count += 1
            return JSONResponse(
                {"jsonrpc": "2.0", "id": data["id"], "result": INIT_RESPONSE},
                headers={"mcp-session-id": f"session-{initialize_count}"},
            )
        if method == "notifications/initialized":
            return Response(status_code=202)
        if method == "tools/list" and session_id == "session-1":
            old_requests_started += 1
            if old_requests_started == 2:
                old_requests_ready.set()
            await release_old_requests.wait()
            return Response(status_code=404)
        if method == "tools/list" and session_id == "session-2":
            return JSONResponse({"jsonrpc": "2.0", "id": data["id"], "result": {"tools": []}})
        return Response(status_code=500)

    app = Starlette(debug=True, routes=[Route("/mcp", handle_mcp_request, methods=["POST"])])
    results: list[types.ListToolsResult] = []

    async def append_list_tools_result(session: ClientSession) -> None:
        results.append(await session.list_tools())

    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                async with anyio.create_task_group() as task_group:
                    task_group.start_soon(append_list_tools_result, session)
                    task_group.start_soon(append_list_tools_result, session)
                    with anyio.fail_after(5):
                        await old_requests_ready.wait()
                    release_old_requests.set()

    assert [result.tools for result in results] == [[], []]
    assert requests.count(("initialize", None)) == 2
    assert requests.count(("notifications/initialized", "session-2")) == 1
    assert requests.count(("tools/list", "session-2")) == 2
