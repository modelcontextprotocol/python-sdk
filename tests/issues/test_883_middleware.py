"""Regression test for issue #883: AssertionError when using Starlette middleware.

BaseHTTPMiddleware expects http.response.body messages, but the SSE handler
sends raw ASGI events, which triggers "AssertionError: Unexpected message"
when the SSE endpoint is wrapped as a regular Starlette endpoint.

The fix uses an ASGI-compatible callable class (HandleSseAsgi) instead of a
Starlette endpoint wrapper, so the SSE handler bypasses middleware response
body wrapping.
"""

import multiprocessing
import socket
from collections.abc import Generator

import anyio
import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from tests.test_helpers import wait_for_server


class PassthroughMiddleware(BaseHTTPMiddleware):  # pragma: no cover
    """A simple pass-through middleware that triggers BaseHTTPMiddleware wrapping."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        return await call_next(request)


@pytest.fixture
def server_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_server_with_middleware(server_port: int) -> None:  # pragma: no cover
    """Create an MCP server wrapped in Starlette BaseHTTPMiddleware."""
    mcp_server = MCPServer("test-883")
    transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    sse_app = mcp_server.sse_app(transport_security=transport_security, host="0.0.0.0")

    # This is the exact scenario that triggers #883:
    # BaseHTTPMiddleware wrapping a Starlette app containing SSE endpoints
    app = Starlette(middleware=[Middleware(PassthroughMiddleware)])
    app.mount("/", sse_app)

    server = uvicorn.Server(config=uvicorn.Config(app=app, host="127.0.0.1", port=server_port, log_level="error"))
    server.run()


@pytest.fixture()
def middleware_server(server_port: int) -> Generator[None, None, None]:
    proc = multiprocessing.Process(
        target=run_server_with_middleware,
        kwargs={"server_port": server_port},
        daemon=True,
    )
    proc.start()
    wait_for_server(server_port)
    yield
    proc.kill()
    proc.join(timeout=2)


@pytest.mark.anyio
async def test_sse_with_middleware_no_assertion_error(middleware_server: None, server_port: int) -> None:
    """Verify SSE endpoint works when Starlette BaseHTTPMiddleware is applied.

    Before the fix, this would raise:
        AssertionError: Unexpected message type 'http.response.body'
    """
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{server_port}") as client:
        with anyio.fail_after(5):
            async with client.stream("GET", "/sse") as response:  # pragma: no branch
                assert response.status_code == 200
                assert "text/event-stream" in response.headers.get("content-type", "")

                # Read the first event to confirm SSE is streaming properly
                line_number = 0
                async for line in response.aiter_lines():  # pragma: no branch
                    if line_number == 0:
                        assert line == "event: endpoint"
                    elif line_number == 1:
                        assert line.startswith("data: /messages/?session_id=")
                    else:
                        break
                    line_number += 1
