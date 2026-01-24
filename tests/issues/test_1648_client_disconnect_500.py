"""Test for issue #1648 - ClientDisconnect returns HTTP 500.

When a client disconnects during a request (network timeout, user cancels, load
balancer timeout, mobile network interruption), the server should handle this
gracefully instead of returning HTTP 500 and logging as ERROR.

ClientDisconnect is a client-side event, not a server failure.
"""

import logging
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

SERVER_NAME = "test_client_disconnect_server"


class SlowServer(Server):
    """Server with a slow tool to allow time for client disconnect."""

    def __init__(self):
        super().__init__(SERVER_NAME)

        @self.list_tools()
        async def handle_list_tools() -> list[Tool]:
            return [
                Tool(
                    name="slow_tool",
                    description="A tool that takes time to respond",
                    input_schema={"type": "object", "properties": {}},
                ),
            ]

        @self.call_tool()
        async def handle_call_tool(name: str, arguments: dict) -> list:
            if name == "slow_tool":
                await anyio.sleep(10)
                return [{"type": "text", "text": "done"}]
            raise ValueError(f"Unknown tool: {name}")


def create_app() -> Starlette:
    """Create a Starlette application for testing."""
    server = SlowServer()
    session_manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=True,
    )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        async with session_manager.run():
            yield

    routes = [Mount("/", app=session_manager.handle_request)]
    return Starlette(routes=routes, lifespan=lifespan)


class ServerThread(threading.Thread):
    """Thread that runs the ASGI application lifespan."""

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

        anyio.run(run_lifespan)

    def stop(self) -> None:
        self._stop_event.set()


@pytest.mark.anyio
async def test_client_disconnect_does_not_produce_500(caplog: pytest.LogCaptureFixture):
    """Client disconnect should not produce HTTP 500 or ERROR log entries.

    Regression test for issue #1648: when a client disconnects mid-request,
    the server was catching the exception with a broad `except Exception` handler,
    logging it as ERROR, and returning HTTP 500.
    """
    app = create_app()
    server_thread = ServerThread(app)
    server_thread.start()

    try:
        await anyio.sleep(0.2)

        with caplog.at_level(logging.DEBUG):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
                timeout=1.0,
            ) as client:
                # Send a tool call that will take a long time, client will timeout
                try:
                    await client.post(
                        "/",
                        json={
                            "jsonrpc": "2.0",
                            "method": "tools/call",
                            "id": "call-1",
                            "params": {"name": "slow_tool", "arguments": {}},
                        },
                        headers={
                            "Accept": "application/json, text/event-stream",
                            "Content-Type": "application/json",
                        },
                    )
                except (httpx.ReadTimeout, httpx.ReadError):
                    pass  # Expected - client timed out

        # Wait briefly for any async error logging to complete
        await anyio.sleep(0.1)

        # Verify no ERROR-level log entries about handling POST requests
        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR and "POST" in r.getMessage()]
        assert not error_records, (
            f"Server logged ERROR for client disconnect: {[r.getMessage() for r in error_records]}"
        )
    finally:
        server_thread.stop()
        server_thread.join(timeout=2)


@pytest.mark.anyio
async def test_server_healthy_after_client_disconnect():
    """Server should remain healthy and accept new requests after a client disconnects."""
    app = create_app()
    server_thread = ServerThread(app)
    server_thread.start()

    try:
        await anyio.sleep(0.2)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            timeout=1.0,
        ) as client:
            # First request - will timeout (simulating client disconnect)
            try:
                await client.post(
                    "/",
                    json={
                        "jsonrpc": "2.0",
                        "method": "tools/call",
                        "id": "call-timeout",
                        "params": {"name": "slow_tool", "arguments": {}},
                    },
                    headers={
                        "Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json",
                    },
                )
            except (httpx.ReadTimeout, httpx.ReadError):
                pass  # Expected - client timed out

        # Create a new client for the second request
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            timeout=5.0,
        ) as client:
            # Second request - should succeed (server still healthy)
            response = await client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "id": "init-after-disconnect",
                    "params": {
                        "clientInfo": {"name": "test-client", "version": "1.0"},
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                    },
                },
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
            )
            assert response.status_code == 200
    finally:
        server_thread.stop()
        server_thread.join(timeout=2)
