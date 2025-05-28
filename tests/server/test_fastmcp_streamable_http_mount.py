"""Test FastMCP streamable_http_app mounts both /mcp and /mcp/ automatically."""

import httpx
import pytest
from mcp.server.fastmcp import FastMCP

@pytest.fixture
def fastmcp_app():
    mcp = FastMCP(name="TestServer")
    app = mcp.streamable_http_app()
    return app

def test_streamable_http_mount_dual_paths(fastmcp_app):
    # Use httpx.AsyncClient with ASGITransport for async test
    async def do_test():
        async with httpx.AsyncClient(app=fastmcp_app, base_url="http://testserver") as client:
            for path in ["/mcp", "/mcp/"]:
                resp = await client.post(
                    path, json={"jsonrpc": "2.0", "method": "initialize", "id": 1}
                )
                assert resp.status_code in (400, 406)
                resp_get = await client.get(path)
                assert resp_get.status_code in (400, 406, 405)
    import anyio
    anyio.run(do_test)
