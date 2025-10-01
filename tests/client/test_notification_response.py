"""
Tests for StreamableHTTP client transport with non-SDK servers.

These tests verify client behavior when interacting with servers
that don't follow SDK conventions.
"""

import json
import multiprocessing
import socket
import time
from collections.abc import Generator

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.session import RequestResponder
from mcp.types import ClientNotification, RootsListChangedNotification


def create_non_sdk_server_app() -> Starlette:
    """Create a minimal server that doesn't follow SDK conventions."""

    async def handle_mcp_request(request: Request) -> Response:
        """Handle MCP requests with non-standard responses."""
        try:
            body = await request.body()
            data = json.loads(body)

            # Handle initialize request normally
            if data.get("method") == "initialize":
                response_data = {
                    "jsonrpc": "2.0",
                    "id": data["id"],
                    "result": {
                        "serverInfo": {"name": "test-non-sdk-server", "version": "1.0.0"},
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                    },
                }
                return JSONResponse(response_data)

            # For notifications, return 204 No Content (non-SDK behavior)
            if "id" not in data:
                return Response(status_code=204, headers={"Content-Type": "application/json"})

            # Default response for other requests
            return JSONResponse(
                {"jsonrpc": "2.0", "id": data.get("id"), "error": {"code": -32601, "message": "Method not found"}}
            )

        except Exception as e:
            return JSONResponse({"error": f"Server error: {str(e)}"}, status_code=500)

    app = Starlette(
        debug=True,
        routes=[
            Route("/mcp", handle_mcp_request, methods=["POST"]),
        ],
    )
    return app


def run_non_sdk_server(port: int) -> None:
    """Run the non-SDK server in a separate process."""
    app = create_non_sdk_server_app()
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="error",  # Reduce noise in tests
    )
    server = uvicorn.Server(config=config)
    server.run()


@pytest.fixture
def non_sdk_server_port() -> int:
    """Get an available port for the test server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def non_sdk_server(non_sdk_server_port: int) -> Generator[None, None, None]:
    """Start a non-SDK server for testing."""
    proc = multiprocessing.Process(target=run_non_sdk_server, kwargs={"port": non_sdk_server_port}, daemon=True)
    proc.start()

    # Wait for server to be ready
    start_time = time.time()
    while time.time() - start_time < 10:
        try:
            with socket.create_connection(("127.0.0.1", non_sdk_server_port), timeout=0.1):
                break
        except (TimeoutError, ConnectionRefusedError):
            time.sleep(0.1)
    else:
        proc.kill()
        proc.join(timeout=2)
        pytest.fail("Server failed to start within 10 seconds")

    yield

    proc.kill()
    proc.join(timeout=2)


@pytest.mark.anyio
async def test_non_compliant_notification_response(non_sdk_server: None, non_sdk_server_port: int) -> None:
    """
    This test verifies that the client ignores unexpected responses to notifications: the spec states they should
    either be 202 + no response body, or 4xx + optional error body
    (https://modelcontextprotocol.io/specification/2025-06-18/basic/transports#sending-messages-to-the-server),
    but some servers wrongly return other 2xx codes (e.g. 204). For now we simply ignore unexpected responses
    (aligning behaviour w/ the TS SDK).
    """
    server_url = f"http://127.0.0.1:{non_sdk_server_port}/mcp"
    returned_exception = None

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ):
        nonlocal returned_exception
        if isinstance(message, Exception):
            returned_exception = message

    async with streamable_http_client(server_url) as (read_stream, write_stream, _):
        async with ClientSession(
            read_stream,
            write_stream,
            message_handler=message_handler,
        ) as session:
            # Initialize should work normally
            await session.initialize()

            # The test server returns a 204 instead of the expected 202
            await session.send_notification(
                ClientNotification(RootsListChangedNotification(method="notifications/roots/list_changed"))
            )

    if returned_exception:
        pytest.fail(f"Server encountered an exception: {returned_exception}")
