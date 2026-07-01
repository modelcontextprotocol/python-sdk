"""Test for issue #1269 - FastMCP server death on client HEAD calls.

HEAD (and other unsupported HTTP methods) sent to the MCP endpoint must
return 405 Method Not Allowed without creating a transport or spawning
background tasks.  Before the fix, such requests in stateless mode caused
a ClosedResourceError in the message router because the transport was
terminated while the router task was still running.

See: https://github.com/modelcontextprotocol/python-sdk/issues/1269
"""

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager


def _create_app(*, stateless: bool) -> Starlette:
    """Create a minimal Starlette app backed by a StreamableHTTPSessionManager.

    No lifespan is needed because unsupported methods are rejected before
    the session manager checks for a running task group.
    """
    server = Server("test_head_crash")
    session_manager = StreamableHTTPSessionManager(
        app=server,
        stateless=stateless,
    )

    return Starlette(
        routes=[Mount("/", app=session_manager.handle_request)],
    )


@pytest.mark.anyio
@pytest.mark.parametrize("stateless", [True, False])
async def test_head_request_returns_405(stateless: bool) -> None:
    """HEAD / must return 405 without creating a transport."""
    app = _create_app(stateless=stateless)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        timeout=5.0,
    ) as client:
        response = await client.head("/")
        assert response.status_code == 405


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["PUT", "PATCH", "OPTIONS"])
async def test_unsupported_methods_return_405(method: str) -> None:
    """Other unsupported HTTP methods also return 405 without crashing."""
    app = _create_app(stateless=True)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        timeout=5.0,
    ) as client:
        response = await client.request(method, "/")
        assert response.status_code == 405
        assert "GET" in response.headers.get("allow", "")
        assert "POST" in response.headers.get("allow", "")
        assert "DELETE" in response.headers.get("allow", "")
