"""Test for issue #1641 - Accept header wildcard support.

The MCP server was rejecting requests with wildcard Accept headers like `*/*`
or `application/*`, returning 406 Not Acceptable. Per RFC 9110 Section 12.5.1,
wildcard media types are valid and should match the required content types.
"""

import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import anyio
import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Tool

SERVER_NAME = "test_accept_wildcard_server"

# Suppress warnings from unclosed MemoryObjectReceiveStream in stateless transport mode
# (pre-existing issue, not related to the Accept header fix)
pytestmark = [
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

INIT_REQUEST = {
    "jsonrpc": "2.0",
    "method": "initialize",
    "id": "init-1",
    "params": {
        "clientInfo": {"name": "test-client", "version": "1.0"},
        "protocolVersion": "2025-03-26",
        "capabilities": {},
    },
}


class SimpleServer(Server):
    def __init__(self):
        super().__init__(SERVER_NAME)

        @self.list_tools()
        async def handle_list_tools() -> list[Tool]:  # pragma: no cover
            return []


def create_app(json_response: bool = False) -> Starlette:
    server = SimpleServer()
    session_manager = StreamableHTTPSessionManager(
        app=server,
        json_response=json_response,
        stateless=True,
    )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        async with session_manager.run():
            yield

    routes = [Mount("/", app=session_manager.handle_request)]
    return Starlette(routes=routes, lifespan=lifespan)


class ServerThread(threading.Thread):
    def __init__(self, app: Starlette):
        super().__init__(daemon=True)
        self.app = app
        self._stop_event = threading.Event()

    def run(self) -> None:
        async def run_lifespan():
            lifespan_context = getattr(self.app.router, "lifespan_context", None)
            assert lifespan_context is not None
            async with lifespan_context(self.app):
                while not self._stop_event.is_set():
                    await anyio.sleep(0.1)

        try:
            anyio.run(run_lifespan)
        except BaseException:  # pragma: no cover
            # Suppress cleanup exceptions (e.g., ResourceWarning from
            # unclosed streams in stateless transport mode)
            pass

    def stop(self) -> None:
        self._stop_event.set()


@pytest.mark.anyio
async def test_accept_wildcard_star_star_json_mode():
    """Accept: */* should be accepted in JSON response mode."""
    app = create_app(json_response=True)
    server_thread = ServerThread(app)
    server_thread.start()

    try:
        await anyio.sleep(0.2)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/",
                json=INIT_REQUEST,
                headers={"Accept": "*/*", "Content-Type": "application/json"},
            )
            assert response.status_code == 200
    finally:
        server_thread.stop()
        server_thread.join(timeout=2)


@pytest.mark.anyio
async def test_accept_wildcard_star_star_sse_mode():
    """Accept: */* should be accepted in SSE response mode (satisfies both JSON and SSE)."""
    app = create_app(json_response=False)
    server_thread = ServerThread(app)
    server_thread.start()

    try:
        await anyio.sleep(0.2)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/",
                json=INIT_REQUEST,
                headers={"Accept": "*/*", "Content-Type": "application/json"},
            )
            assert response.status_code == 200
    finally:
        server_thread.stop()
        server_thread.join(timeout=2)


@pytest.mark.anyio
async def test_accept_application_wildcard():
    """Accept: application/* should satisfy the application/json requirement."""
    app = create_app(json_response=True)
    server_thread = ServerThread(app)
    server_thread.start()

    try:
        await anyio.sleep(0.2)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/",
                json=INIT_REQUEST,
                headers={"Accept": "application/*", "Content-Type": "application/json"},
            )
            assert response.status_code == 200
    finally:
        server_thread.stop()
        server_thread.join(timeout=2)


@pytest.mark.anyio
async def test_accept_text_wildcard_with_json():
    """Accept: application/json, text/* should satisfy both requirements in SSE mode."""
    app = create_app(json_response=False)
    server_thread = ServerThread(app)
    server_thread.start()

    try:
        await anyio.sleep(0.2)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/",
                json=INIT_REQUEST,
                headers={
                    "Accept": "application/json, text/*",
                    "Content-Type": "application/json",
                },
            )
            assert response.status_code == 200
    finally:
        server_thread.stop()
        server_thread.join(timeout=2)


@pytest.mark.anyio
async def test_accept_wildcard_with_quality_parameter():
    """Accept: */*;q=0.8 should be accepted (quality parameters stripped before matching)."""
    app = create_app(json_response=True)
    server_thread = ServerThread(app)
    server_thread.start()

    try:
        await anyio.sleep(0.2)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/",
                json=INIT_REQUEST,
                headers={"Accept": "*/*;q=0.8", "Content-Type": "application/json"},
            )
            assert response.status_code == 200
    finally:
        server_thread.stop()
        server_thread.join(timeout=2)


@pytest.mark.anyio
async def test_accept_invalid_still_rejected():
    """Accept: text/plain should still be rejected with 406."""
    app = create_app(json_response=True)
    server_thread = ServerThread(app)
    server_thread.start()

    try:
        await anyio.sleep(0.2)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/",
                json=INIT_REQUEST,
                headers={"Accept": "text/plain", "Content-Type": "application/json"},
            )
            assert response.status_code == 406
    finally:
        server_thread.stop()
        server_thread.join(timeout=2)


@pytest.mark.anyio
async def test_accept_partial_wildcard_sse_mode_rejected():
    """Accept: application/* alone should be rejected in SSE mode (missing text/event-stream)."""
    app = create_app(json_response=False)
    server_thread = ServerThread(app)
    server_thread.start()

    try:
        await anyio.sleep(0.2)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/",
                json=INIT_REQUEST,
                headers={"Accept": "application/*", "Content-Type": "application/json"},
            )
            # application/* matches JSON but not SSE, should be rejected
            assert response.status_code == 406
    finally:
        server_thread.stop()
        server_thread.join(timeout=2)
