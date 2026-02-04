import httpx
import pytest

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer


@pytest.fixture
def server() -> MCPServer:
    mcp = MCPServer("test_server")

    @mcp.tool()
    async def my_tool() -> str:
        return "test"

    return mcp


HOST = "testserver"


@pytest.mark.anyio
async def test_streamable_http_server_cleanup(server: MCPServer):
    mcp_app = server.streamable_http_app(host=HOST)
    async with (
        mcp_app.router.lifespan_context(mcp_app),
        httpx.ASGITransport(mcp_app) as transport,
        httpx.AsyncClient(transport=transport) as client,
        streamable_http_client(f"http://{HOST}/mcp", http_client=client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        await session.call_tool("my_tool", arguments={})
