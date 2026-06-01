import anyio
import httpx
import pytest

from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER
from mcp.types import (
    INVALID_REQUEST,
    LATEST_PROTOCOL_VERSION,
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)


@pytest.mark.anyio
async def test_streamable_http_duplicate_request_id_returns_409_and_preserves_in_flight_request() -> None:
    started = anyio.Event()
    release = anyio.Event()

    async def handle_list_tools(
        ctx: ServerRequestContext[object],
        params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                Tool(
                    name="slow_tool",
                    description="Blocks until released by the test",
                    input_schema={"type": "object", "properties": {}},
                )
            ]
        )

    async def handle_call_tool(
        ctx: ServerRequestContext[object],
        params: CallToolRequestParams,
    ) -> CallToolResult:
        started.set()
        await release.wait()
        return CallToolResult(content=[TextContent(type="text", text="ok")])

    server = Server("test-duplicate-request-id", on_list_tools=handle_list_tools, on_call_tool=handle_call_tool)
    mcp_app = server.streamable_http_app(json_response=True, host="testserver")

    async with (
        mcp_app.router.lifespan_context(mcp_app),
        httpx.ASGITransport(mcp_app) as transport,
        httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0) as client,
    ):
        base_headers = {"Accept": "application/json", "Content-Type": "application/json"}

        init_response = await client.post(
            "/mcp",
            headers=base_headers,
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "id": "init-1",
                "params": {
                    "clientInfo": {"name": "test-client", "version": "0"},
                    "protocolVersion": LATEST_PROTOCOL_VERSION,
                    "capabilities": {},
                },
            },
        )
        assert init_response.status_code == 200
        session_id = init_response.headers.get(MCP_SESSION_ID_HEADER)
        assert session_id is not None

        session_headers = {**base_headers, MCP_SESSION_ID_HEADER: session_id}

        initialized = await client.post(
            "/mcp",
            headers=session_headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        assert initialized.status_code == 202

        request_id = "dup-id-1"
        slow_response: httpx.Response | None = None

        async def run_slow_request() -> None:
            nonlocal slow_response
            slow_response = await client.post(
                "/mcp",
                headers=session_headers,
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": request_id,
                    "params": {"name": "slow_tool", "arguments": {}},
                },
            )

        async with anyio.create_task_group() as tg:
            tg.start_soon(run_slow_request)
            with anyio.fail_after(5):
                await started.wait()

            duplicate = await client.post(
                "/mcp",
                headers=session_headers,
                json={"jsonrpc": "2.0", "method": "ping", "id": request_id, "params": {}},
            )
            assert duplicate.status_code == 409
            duplicate_body = duplicate.json()
            assert duplicate_body["jsonrpc"] == "2.0"
            assert duplicate_body["id"] == request_id
            assert duplicate_body["error"]["code"] == INVALID_REQUEST

            release.set()

        assert slow_response is not None
        assert slow_response.status_code == 200
        slow_body = slow_response.json()
        assert slow_body["jsonrpc"] == "2.0"
        assert slow_body["id"] == request_id
        assert slow_body["result"]["content"][0]["text"] == "ok"
