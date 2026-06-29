"""StreamableHTTP client behavior against servers that don't follow SDK conventions."""

import json

import httpx
import mcp_types as types
import pytest
from mcp_types import RootsListChangedNotification
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from mcp import ClientSession, MCPError
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.session import RequestResponder

pytestmark = pytest.mark.anyio

INIT_RESPONSE = {
    "serverInfo": {"name": "test-non-sdk-server", "version": "1.0.0"},
    "protocolVersion": "2024-11-05",
    "capabilities": {},
}


def _init_json_response(data: dict[str, object]) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": data["id"], "result": INIT_RESPONSE})


def _create_non_sdk_server_app() -> Starlette:
    async def handle_mcp_request(request: Request) -> Response:
        body = await request.body()
        data = json.loads(body)

        if data.get("method") == "initialize":
            return _init_json_response(data)

        # Notifications get 204 instead of the spec's 202
        if "id" not in data:
            return Response(status_code=204, headers={"Content-Type": "application/json"})

        return JSONResponse(  # pragma: no cover
            {"jsonrpc": "2.0", "id": data.get("id"), "error": {"code": -32601, "message": "Method not found"}}
        )

    return Starlette(debug=True, routes=[Route("/mcp", handle_mcp_request, methods=["POST"])])


def _create_unexpected_content_type_app() -> Starlette:
    async def handle_mcp_request(request: Request) -> Response:
        body = await request.body()
        data = json.loads(body)

        if data.get("method") == "initialize":
            return _init_json_response(data)

        if "id" not in data:
            return Response(status_code=202)

        return Response(content="this is plain text, not json or sse", status_code=200, media_type="text/plain")

    return Starlette(debug=True, routes=[Route("/mcp", handle_mcp_request, methods=["POST"])])


async def test_non_compliant_notification_response() -> None:
    """Non-202 2xx notification responses (e.g. 204) are ignored, matching the TS SDK.

    Spec: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports#sending-messages-to-the-server
    """
    returned_exception = None

    async def message_handler(  # pragma: no cover
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        nonlocal returned_exception
        if isinstance(message, Exception):
            returned_exception = message

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_create_non_sdk_server_app())) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream, message_handler=message_handler) as session:
                await session.initialize()

                await session.send_notification(RootsListChangedNotification(method="notifications/roots/list_changed"))

    if returned_exception:  # pragma: no cover
        pytest.fail(f"Server encountered an exception: {returned_exception}")


async def test_unexpected_content_type_sends_jsonrpc_error() -> None:
    """The synthesized JSONRPCError resolves the pending request immediately instead of hanging until timeout."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_create_unexpected_content_type_app())) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()

                with pytest.raises(MCPError, match="Unexpected content type: text/plain"):  # pragma: no branch
                    await session.list_tools()


def _create_http_error_app(error_status: int, *, error_on_notifications: bool = False) -> Starlette:
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
    """The HTTP error becomes a JSONRPCError rather than an unhandled httpx.HTTPStatusError that hangs the caller."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_create_http_error_app(500))) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()

                with pytest.raises(MCPError, match="Server returned an error response"):  # pragma: no branch
                    await session.list_tools()


async def test_http_error_on_notification_does_not_hang() -> None:
    """With no pending request to unblock, the client silently ignores the error."""
    app = _create_http_error_app(500, error_on_notifications=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()

                await session.send_notification(RootsListChangedNotification(method="notifications/roots/list_changed"))


def _create_invalid_json_response_app() -> Starlette:
    async def handle_mcp_request(request: Request) -> Response:
        body = await request.body()
        data = json.loads(body)

        if data.get("method") == "initialize":
            return _init_json_response(data)

        if "id" not in data:
            return Response(status_code=202)

        return Response(content="not valid json{{{", status_code=200, media_type="application/json")

    return Starlette(debug=True, routes=[Route("/mcp", handle_mcp_request, methods=["POST"])])


async def test_invalid_json_response_sends_jsonrpc_error() -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_create_invalid_json_response_app())) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()

                with pytest.raises(MCPError, match="Failed to parse JSON response"):  # pragma: no branch
                    await session.list_tools()


def _create_non_2xx_json_body_app(status: int, body: bytes) -> Starlette:
    """Server returning a fixed non-2xx status + JSON body; init sets `mcp-session-id` so later
    requests count as in-session (needed for the 404 → session-terminated mapping)."""

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
    """SDK-defined: a JSON-RPC error in a non-2xx body with `id: null` is rewrapped under the
    pending request's id, so the caller sees the server's error code, not the generic fallback."""
    body = json.dumps(
        {"jsonrpc": "2.0", "id": None, "error": {"code": types.METHOD_NOT_FOUND, "message": "nope"}}
    ).encode()
    app = _create_non_2xx_json_body_app(400, body)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()
                with pytest.raises(MCPError) as exc:
                    await session.list_tools()
                assert exc.value.error.code == types.METHOD_NOT_FOUND


async def test_client_falls_back_to_generic_error_when_non_2xx_body_is_a_jsonrpc_result() -> None:
    """SDK-defined: a non-2xx body that parses as a JSON-RPC result (not an error) falls through
    to the generic INTERNAL_ERROR fallback rather than being treated as the request's reply."""
    app = _create_non_2xx_json_body_app(400, b'{"jsonrpc":"2.0","id":1,"result":{}}')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()
                with pytest.raises(MCPError) as exc:
                    await session.list_tools()
                assert exc.value.error.code == types.INTERNAL_ERROR


async def test_client_falls_back_to_session_terminated_when_404_body_is_malformed_json() -> None:
    """SDK-defined: a malformed 404 body is swallowed; the status-derived session-terminated
    fallback resolves the pending request rather than the parse failure propagating."""
    app = _create_non_2xx_json_body_app(404, b"not valid json{{{")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()
                with pytest.raises(MCPError) as exc:
                    await session.list_tools()
                assert exc.value.error.code == types.INVALID_REQUEST
