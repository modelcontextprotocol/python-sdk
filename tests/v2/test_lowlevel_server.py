"""E2E tests for the V2 low-level server over StreamableHTTP.

Tests the full stack: LowLevelServer → ServerRunner → StreamableHTTPHandler → Starlette,
exercised via httpx's ASGI transport (real HTTP semantics, no running server).
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import anyio
import httpx
import pytest

from mcp_v2.context import RequestContext
from mcp_v2.runner import ServerRunner
from mcp_v2.server import LowLevelServer
from mcp_v2.transport.httphandler import StreamableHTTPHandler
from mcp_v2.transport.starlette import create_starlette_app
from mcp_v2.types.json_rpc import JSONRPCRequest
from mcp_v2.types.tools import CallToolRequestParams, CallToolResult, JsonSchema, ListToolsResult, Tool

pytestmark = pytest.mark.anyio


def _make_server() -> LowLevelServer:
    """Create a test server with tools/list and tools/call handlers."""
    server = LowLevelServer(name="test-server", version="0.1.0")

    @server.request_handler("tools/list")
    async def handle_list_tools(ctx: RequestContext, request: JSONRPCRequest) -> ListToolsResult:
        schema = JsonSchema(properties={"message": {"type": "string"}})
        return ListToolsResult(
            tools=[
                Tool(name="echo", description="Echoes the input", input_schema=schema),
                Tool(name="notify_and_echo", description="Sends a notification then echoes", input_schema=schema),
            ]
        )

    @server.request_handler("tools/call")
    async def handle_call_tool(ctx: RequestContext, request: JSONRPCRequest) -> CallToolResult:
        from mcp_v2.types.content import TextContent

        params = CallToolRequestParams.model_validate(request.params)
        message = (params.arguments or {}).get("message", "")

        if params.name == "notify_and_echo":
            # Send a progress notification — this forces SSE mode in HTTP
            await ctx.send_notification("notifications/progress", {"progress": 1, "total": 1})

        return CallToolResult(content=[TextContent(text=message)])

    return server


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """Create an httpx client with the Starlette app, lifespan manually started."""
    server = _make_server()
    app = create_starlette_app(server)

    # httpx ASGITransport doesn't trigger lifespan, so we do it manually:
    # start the runner and handler, then set them on app.state
    runner = ServerRunner(server)
    async with runner.run() as running:
        async with anyio.create_task_group() as tg:
            app.state.handler = StreamableHTTPHandler(running, tg)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http_client:
                yield http_client
                tg.cancel_scope.cancel()


def _init_request(request_id: int = 1) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        },
    }


def _initialized_notification() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }


async def _do_init(client: httpx.AsyncClient) -> str:
    """Perform init handshake, return session_id."""
    resp = await client.post("/mcp", json=_init_request())
    assert resp.status_code == 200
    session_id = resp.headers["mcp-session-id"]

    await client.post(
        "/mcp",
        json=_initialized_notification(),
        headers={"mcp-session-id": session_id},
    )
    return session_id


async def test_initialize_handshake(client: httpx.AsyncClient) -> None:
    resp = await client.post("/mcp", json=_init_request())

    assert resp.status_code == 200
    data = resp.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 1
    result = data["result"]
    assert result["protocolVersion"] == "2025-11-25"
    assert result["serverInfo"]["name"] == "test-server"
    assert result["serverInfo"]["version"] == "0.1.0"
    assert "tools" in result["capabilities"]


async def test_list_tools(client: httpx.AsyncClient) -> None:
    session_id = await _do_init(client)

    resp = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers={"mcp-session-id": session_id},
    )
    assert resp.status_code == 200
    data = resp.json()
    tools = data["result"]["tools"]
    assert len(tools) == 2
    assert tools[0]["name"] == "echo"
    assert tools[1]["name"] == "notify_and_echo"


async def test_call_tool_json_response(client: httpx.AsyncClient) -> None:
    """A tool that doesn't send notifications returns a plain JSON response."""
    session_id = await _do_init(client)

    resp = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"message": "hello world"}},
        },
        headers={"mcp-session-id": session_id},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    data = resp.json()
    assert data["result"]["content"][0]["text"] == "hello world"
    assert data["result"]["isError"] is False


async def test_call_tool_sse_response(client: httpx.AsyncClient) -> None:
    """A tool that sends a notification forces an SSE stream response."""
    session_id = await _do_init(client)

    async with client.stream(
        "POST",
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "notify_and_echo", "arguments": {"message": "streamed"}},
        },
        headers={"mcp-session-id": session_id},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        # Collect all SSE events
        events = [line[6:] async for line in resp.aiter_lines() if line.startswith("data: ")]

        # Should have 2 events: the notification and the final result
        assert len(events) == 2

        # First event is the progress notification
        notif = json.loads(events[0])
        assert notif["method"] == "notifications/progress"
        assert notif["params"]["progress"] == 1

        # Second event is the tool result
        result = json.loads(events[1])
        assert result["result"]["content"][0]["text"] == "streamed"
        assert result["id"] == 4


async def test_method_not_found(client: httpx.AsyncClient) -> None:
    session_id = await _do_init(client)

    resp = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 5, "method": "nonexistent/method"},
        headers={"mcp-session-id": session_id},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == -32601  # METHOD_NOT_FOUND


async def test_session_delete(client: httpx.AsyncClient) -> None:
    session_id = await _do_init(client)

    # Delete existing session
    resp = await client.delete("/mcp", headers={"mcp-session-id": session_id})
    assert resp.status_code == 200

    # Delete non-existent session
    resp = await client.delete("/mcp", headers={"mcp-session-id": "nonexistent"})
    assert resp.status_code == 404
