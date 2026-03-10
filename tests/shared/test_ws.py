"""Tests for the WebSocket transport.

The smoke test (``test_ws_client_basic_connection``) runs the full WS stack
end-to-end over a real TCP connection and is what provides coverage of
``src/mcp/client/websocket.py``.

The remaining tests verify transport-agnostic MCP semantics (error
propagation, client-side timeouts) and use the in-memory ``Client`` transport
to avoid the cost and flakiness of real network servers.
"""

from collections.abc import Generator
from urllib.parse import urlparse

import anyio
import pytest
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket

from mcp import Client, MCPError
from mcp.client.session import ClientSession
from mcp.client.websocket import websocket_client
from mcp.server import Server, ServerRequestContext
from mcp.server.websocket import websocket_server
from mcp.types import (
    EmptyResult,
    InitializeResult,
    ReadResourceRequestParams,
    ReadResourceResult,
    TextResourceContents,
)
from tests.test_helpers import run_uvicorn_in_thread

SERVER_NAME = "test_server_for_WS"

pytestmark = pytest.mark.anyio


# --- WebSocket transport smoke test (real TCP) -------------------------------


def make_server_app() -> Starlette:
    srv = Server(SERVER_NAME)

    async def handle_ws(websocket: WebSocket) -> None:
        async with websocket_server(websocket.scope, websocket.receive, websocket.send) as streams:
            await srv.run(streams[0], streams[1], srv.create_initialization_options())

    return Starlette(routes=[WebSocketRoute("/ws", endpoint=handle_ws)])


@pytest.fixture
def ws_server_url() -> Generator[str, None, None]:
    with run_uvicorn_in_thread(make_server_app()) as base_url:
        yield base_url.replace("http://", "ws://") + "/ws"


async def test_ws_client_basic_connection(ws_server_url: str) -> None:
    async with websocket_client(ws_server_url) as streams:
        async with ClientSession(*streams) as session:
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.server_info.name == SERVER_NAME

            ping_result = await session.send_ping()
            assert isinstance(ping_result, EmptyResult)


# --- In-memory tests (transport-agnostic MCP semantics) ----------------------


async def handle_read_resource(ctx: ServerRequestContext, params: ReadResourceRequestParams) -> ReadResourceResult:
    parsed = urlparse(str(params.uri))
    if parsed.scheme == "foobar":
        return ReadResourceResult(
            contents=[TextResourceContents(uri=str(params.uri), text=f"Read {parsed.netloc}", mime_type="text/plain")]
        )
    elif parsed.scheme == "slow":
        # Block indefinitely so the client-side fail_after() fires; the pending
        # server task is cancelled when the Client context manager exits.
        await anyio.sleep_forever()
    raise MCPError(code=404, message="OOPS! no resource with that URI was found")


@pytest.fixture
def server() -> Server:
    return Server(SERVER_NAME, on_read_resource=handle_read_resource)


async def test_ws_client_happy_request_and_response(server: Server) -> None:
    async with Client(server) as client:
        result = await client.read_resource("foobar://example")
        assert isinstance(result, ReadResourceResult)
        assert isinstance(result.contents, list)
        assert len(result.contents) > 0
        assert isinstance(result.contents[0], TextResourceContents)
        assert result.contents[0].text == "Read example"


async def test_ws_client_exception_handling(server: Server) -> None:
    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("unknown://example")
        assert exc_info.value.error.code == 404


async def test_ws_client_timeout(server: Server) -> None:
    async with Client(server) as client:
        with pytest.raises(TimeoutError):
            with anyio.fail_after(0.1):
                await client.read_resource("slow://example")

        # Session remains usable after a client-side timeout abandons a request.
        with anyio.fail_after(5):
            result = await client.read_resource("foobar://example")
            assert isinstance(result, ReadResourceResult)
            assert isinstance(result.contents, list)
            assert len(result.contents) > 0
            assert isinstance(result.contents[0], TextResourceContents)
            assert result.contents[0].text == "Read example"
