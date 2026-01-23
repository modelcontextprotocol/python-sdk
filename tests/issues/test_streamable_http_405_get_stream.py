"""Test for streamable_http client handling of 405 Method Not Allowed on GET requests.

This test verifies the fix for the race condition where the client hangs when connecting
to servers (like GitHub MCP) that don't support GET for SSE events.
"""

import logging

import anyio
import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import InitializeResult


async def mock_github_endpoint(request: Request) -> Response:
    """Mock endpoint that returns 405 for GET (like GitHub MCP)."""
    if request.method == "GET":
        return Response(
            content="Method Not Allowed",
            status_code=405,
            headers={"Allow": "POST, DELETE"},
        )
    elif request.method == "POST":
        body = await request.json()
        if body.get("method") == "initialize":
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "serverInfo": {"name": "mock_github_server", "version": "1.0"},
                        "capabilities": {"tools": {}},
                    },
                },
                headers={"mcp-session-id": "test-session"},
            )
        elif body.get("method") == "notifications/initialized":
            return Response(status_code=202)
        elif body.get("method") == "tools/list":
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "result": {
                        "tools": [
                            {
                                "name": "test_tool",
                                "description": "A test tool",
                                "inputSchema": {"type": "object", "properties": {}},
                            }
                        ]
                    },
                }
            )
    return Response(status_code=405)

@pytest.mark.anyio
async def test_405_get_stream_does_not_hang(caplog: pytest.LogCaptureFixture):
    """Test that client handles 405 on GET gracefully and doesn't hang."""
    app = Starlette(routes=[Route("/mcp", mock_github_endpoint, methods=["GET", "POST"])])

    with caplog.at_level(logging.INFO):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=5.0
        ) as http_client:
            async with streamable_http_client("http://testserver/mcp", http_client=http_client) as (
                read_stream,
                write_stream,
                _,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    # Initialize sends the initialized notification internally
                    init_result = await session.initialize()
                    assert isinstance(init_result, InitializeResult)

                    # Give the GET stream task time to fail with 405
                    await anyio.sleep(0.2)

                    # This should not hang and will now complete successfully
                    tools_result = await session.list_tools()
                    assert len(tools_result.tools) == 1
                    assert tools_result.tools[0].name == "test_tool"

    # Verify the 405 was logged and no retries occurred
    log_messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Server does not support GET for SSE events (405 Method Not Allowed)" in msg for msg in log_messages
    ), f"Expected 405 log message not found in: {log_messages}"

    reconnect_messages = [msg for msg in log_messages if "reconnecting" in msg.lower()]
    assert len(reconnect_messages) == 0, f"Should not retry on 405, but found: {reconnect_messages}"