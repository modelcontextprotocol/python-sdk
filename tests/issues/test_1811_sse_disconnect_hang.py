"""Test for issue #1811 - client hangs after SSE disconnection.

When the SSE stream disconnects before the server sends a response (e.g., due to
a read timeout), the client's read_stream_writer was never sent an error message,
causing the client to hang indefinitely on .receive(). The fix sends a JSONRPCError
when the stream disconnects without a resumable event ID.
"""

import multiprocessing
import socket
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import anyio
import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import McpError
from mcp.types import TextContent, Tool
from tests.test_helpers import wait_for_server

SERVER_NAME = "test_sse_disconnect_server"


def get_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def create_slow_server_app() -> Starlette:
    """Create a server with a tool that takes a long time to respond."""
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return [
            Tool(
                name="slow_tool",
                description="A tool that takes a long time",
                input_schema={"type": "object", "properties": {}},
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, object]) -> list[TextContent]:
        # Sleep long enough that the client timeout fires first
        await anyio.sleep(30)
        return [TextContent(type="text", text="done")]

    session_manager = StreamableHTTPSessionManager(app=server, stateless=True)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        async with session_manager.run():
            yield

    return Starlette(
        routes=[Mount("/mcp", app=session_manager.handle_request)],
        lifespan=lifespan,
    )


def create_fast_server_app() -> Starlette:
    """Create a server with a fast tool for sanity testing."""
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return [
            Tool(
                name="fast_tool",
                description="A fast tool",
                input_schema={"type": "object", "properties": {}},
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, object]) -> list[TextContent]:
        return [TextContent(type="text", text="fast result")]

    session_manager = StreamableHTTPSessionManager(app=server, stateless=True)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        async with session_manager.run():
            yield

    return Starlette(
        routes=[Mount("/mcp", app=session_manager.handle_request)],
        lifespan=lifespan,
    )


def run_server(port: int, slow: bool = True) -> None:
    """Run the server in a separate process."""
    import uvicorn

    app = create_slow_server_app() if slow else create_fast_server_app()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


@pytest.fixture
def slow_server_url():
    """Start the slow server and return its URL."""
    port = get_free_port()
    proc = multiprocessing.Process(target=run_server, args=(port, True), daemon=True)
    proc.start()
    wait_for_server(port)

    yield f"http://127.0.0.1:{port}"

    proc.kill()
    proc.join(timeout=2)


@pytest.fixture
def fast_server_url():
    """Start the fast server and return its URL."""
    port = get_free_port()
    proc = multiprocessing.Process(target=run_server, args=(port, False), daemon=True)
    proc.start()
    wait_for_server(port)

    yield f"http://127.0.0.1:{port}"

    proc.kill()
    proc.join(timeout=2)


@pytest.mark.anyio
async def test_client_receives_error_on_sse_disconnect(slow_server_url: str):
    """Client should receive an error instead of hanging when SSE stream disconnects.

    When the read timeout fires before the server sends a response, the SSE stream
    is closed. Previously, if no event ID had been received, the client would hang
    forever. Now it should raise McpError with the disconnect message.
    """
    # Use a short read timeout so the SSE stream disconnects quickly
    short_timeout_client = httpx.AsyncClient(
        timeout=httpx.Timeout(5.0, read=0.5),
    )

    async with streamable_http_client(
        f"{slow_server_url}/mcp/",
        http_client=short_timeout_client,
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Call the slow tool - the read timeout should fire
            # and the client should receive an error instead of hanging
            with pytest.raises(McpError, match="SSE stream disconnected"):
                await session.call_tool("slow_tool", {})


@pytest.mark.anyio
async def test_fast_tool_still_works_normally(fast_server_url: str):
    """Ensure normal (fast) tool calls still work correctly after the fix."""
    client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))

    async with streamable_http_client(
        f"{fast_server_url}/mcp/",
        http_client=client,
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool("fast_tool", {})
            assert result.content[0].type == "text"
            assert isinstance(result.content[0], TextContent)
            assert result.content[0].text == "fast result"
