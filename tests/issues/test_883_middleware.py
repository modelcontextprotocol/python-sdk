
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.testclient import TestClient
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

class MockMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        return await call_next(request)

def test_883_middleware_sse_no_assertion_error():
    """Test that using MCP SSE with Starlette middleware doesn't cause double-response error."""
    mcp_server = MCPServer("test-server")
    transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    sse_app = mcp_server.sse_app(transport_security=transport_security)
    
    app = Starlette(middleware=[Middleware(MockMiddleware)])
    app.mount("/", sse_app)
    
    client = TestClient(app)
    
    # We use a context manager to ensure the stream is closed quickly
    with client.stream("GET", "/sse") as response:
        assert response.status_code == 200
        # Just check headers are there
        assert "text/event-stream" in response.headers["content-type"]

def test_883_middleware_post_accepted():
    """Test that POST messages work with middleware."""
    mcp_server = MCPServer("test-server")
    transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    sse_app = mcp_server.sse_app(transport_security=transport_security)
    
    app = Starlette(middleware=[Middleware(MockMiddleware)])
    app.mount("/", sse_app)
    
    client = TestClient(app)
    
    # POST to /messages/ (with invalid session, but should not AssertionError)
    response = client.post("/messages/?session_id=00000000000000000000000000000000", json={
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {}
    })
    
    # 404 is expected here as we didn't establish a real session
    assert response.status_code == 404
