"""Tests for StreamableHTTP client transport HTTP error handling.

Verifies that HTTP 4xx/5xx responses are handled gracefully
instead of crashing the program.
"""

import json

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.session import RequestResponder

pytestmark = pytest.mark.anyio

INIT_RESPONSE = {
    "serverInfo": {"name": "test-http-error-server", "version": "1.0.0"},
    "protocolVersion": "2024-11-05",
    "capabilities": {},
}


def _create_401_server_app() -> Starlette:
    """Create a server that returns 401 for non-init requests."""

    async def handle_mcp_request(request: Request) -> Response:
        body = await request.body()
        data = json.loads(body)

        if data.get("method") == "initialize":
            return JSONResponse({"jsonrpc": "2.0", "id": data["id"], "result": INIT_RESPONSE})

        if "id" not in data:
            return Response(status_code=202)

        return Response(status_code=401)

    return Starlette(debug=True, routes=[Route("/mcp", handle_mcp_request, methods=["POST"])])


async def test_http_401_returns_jsonrpc_error() -> None:
    """Test that a 401 response returns a JSONRPC error instead of crashing.

    Regression test for https://github.com/modelcontextprotocol/python-sdk/issues/1295
    """
    returned_exception = None

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        nonlocal returned_exception
        if isinstance(message, Exception):  # pragma: no cover
            returned_exception = message

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_create_401_server_app())) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream, message_handler=message_handler) as session:
                await session.initialize()

                # list_tools should get a JSONRPC error with HTTP status, not crash
                with pytest.raises(Exception) as exc_info:
                    await session.list_tools()
                assert "401" in str(exc_info.value)

    if returned_exception:  # pragma: no cover
        pytest.fail(f"Unexpected exception: {returned_exception}")


def _create_503_server_app() -> Starlette:
    """Create a server that returns 503 for non-init requests."""

    async def handle_mcp_request(request: Request) -> Response:
        body = await request.body()
        data = json.loads(body)

        if data.get("method") == "initialize":
            return JSONResponse({"jsonrpc": "2.0", "id": data["id"], "result": INIT_RESPONSE})

        if "id" not in data:
            return Response(status_code=202)

        return Response(status_code=503)

    return Starlette(debug=True, routes=[Route("/mcp", handle_mcp_request, methods=["POST"])])


async def test_http_503_returns_jsonrpc_error() -> None:
    """Test that a 503 response returns a JSONRPC error instead of crashing."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_create_503_server_app())) as client:
        async with streamable_http_client("http://localhost/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                with pytest.raises(Exception) as exc_info:
                    await session.list_tools()
                assert "503" in str(exc_info.value)
