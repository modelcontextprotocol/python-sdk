"""Smoke test for the WebSocket transport.

Runs the full WS stack end-to-end over a real TCP connection, covering both
``src/mcp/client/websocket.py`` and ``src/mcp/server/websocket.py``. MCP
semantics (error propagation, timeouts, etc.) are transport-agnostic and are
covered in ``tests/client/test_client.py`` and ``tests/issues/test_88_random_error.py``.
"""

from collections.abc import Generator

import pytest
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket

from mcp.client.session import ClientSession
from mcp.client.websocket import websocket_client
from mcp.server import Server
from mcp.server.websocket import websocket_server
from mcp.types import EmptyResult, InitializeResult
from tests.test_helpers import run_uvicorn_in_thread

SERVER_NAME = "test_server_for_WS"


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


@pytest.mark.anyio
async def test_ws_client_basic_connection(ws_server_url: str) -> None:
    async with websocket_client(ws_server_url) as streams:
        async with ClientSession(*streams) as session:
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.server_info.name == SERVER_NAME

            ping_result = await session.send_ping()
            assert isinstance(ping_result, EmptyResult)
