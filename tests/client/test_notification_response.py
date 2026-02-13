"""Tests for StreamableHTTP client transport with non-SDK servers.

These tests verify client behavior when interacting with servers
that don't follow SDK conventions.
"""

import json

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from mcp import ClientSession, MCPError, types
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.session import RequestResponder
from mcp.types import RootsListChangedNotification

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
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_create_unexpected_content_type_app())) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()

                with pytest.raises(MCPError, match="Unexpected content type: text/plain"):  # pragma: no branch
                    await session.list_tools()


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
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_create_invalid_json_response_app())) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()

                with pytest.raises(MCPError, match="Failed to parse JSON response"):  # pragma: no branch
                    await session.list_tools()
