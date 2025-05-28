"""Test FastMCP streamable_http_app mounts both /mcp and /mcp/ automatically."""

import pytest
from starlette.testclient import TestClient
from mcp.server.fastmcp import FastMCP

@pytest.fixture
def fastmcp_app():
    mcp = FastMCP(name="TestServer")
    app = mcp.streamable_http_app()
    return app

def test_streamable_http_mount_dual_paths(fastmcp_app):
    client = TestClient(fastmcp_app)
    for path in ["/mcp", "/mcp/"]:
        # Should return 406 because Accept header is missing, but proves route exists
        resp = client.post(path, json={"jsonrpc": "2.0", "method": "initialize", "id": 1})
        assert resp.status_code in (400, 406)  # 406 Not Acceptable or 400 Bad Request
        # Optionally, test GET as well
        resp_get = client.get(path)
        assert resp_get.status_code in (400, 406, 405)  # 405 if GET not allowed
