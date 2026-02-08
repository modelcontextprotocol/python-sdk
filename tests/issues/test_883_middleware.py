import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings


class MockMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        return await call_next(request)


@pytest.mark.anyio
async def test_883_middleware_sse_no_assertion_error():
    """Test that using MCP SSE with Starlette middleware doesn't cause double-response error."""
    mcp_server = MCPServer("test-server")
    transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    # Using host="0.0.0.0" avoids auto-protection triggering logic for localhost
    sse_app = mcp_server.sse_app(transport_security=transport_security, host="0.0.0.0")

    app = Starlette(middleware=[Middleware(MockMiddleware)])
    # Mount at root to simplify test paths
    app.mount("/", sse_app)

    # Use ASGITransport to properly test the ASGI app stack
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with client.stream("GET", "/sse") as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            # Consume stream a bit or close immediately
            pass


@pytest.mark.anyio
async def test_883_middleware_post_accepted():
    """Test that POST messages work with middleware."""
    mcp_server = MCPServer("test-server")
    transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    sse_app = mcp_server.sse_app(transport_security=transport_security, host="0.0.0.0")

    app = Starlette(middleware=[Middleware(MockMiddleware)])
    app.mount("/", sse_app)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/messages/?session_id=00000000000000000000000000000000",
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        # 404 is expected here as we didn't establish a real session
        assert response.status_code == 404
