import multiprocessing
import socket
import time
from collections.abc import AsyncGenerator, Generator

import anyio
import pytest
import uvicorn
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute

from mcp.client.session import ClientSession
from mcp.client.websocket import websocket_client
from mcp.server import Server
from mcp.server.websocket import websocket_server
from mcp.shared.exceptions import McpError
from mcp.types import (
    EmptyResult,
    ErrorData,
    InitializeResult,
    ReadResourceResult,
    TextContent,
    TextResourceContents,
    Tool,
)

SERVER_NAME = "test_server_for_WS"


@pytest.fixture
def server_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server_url(server_port: int) -> str:
    return f"ws://127.0.0.1:{server_port}"


# Test server implementation
class ServerTest(Server):
    def __init__(self):
        super().__init__(SERVER_NAME)

        @self.read_resource()
        async def handle_read_resource(uri: AnyUrl) -> str | bytes:
            if uri.scheme == "foobar":
                return f"Read {uri.host}"
            elif uri.scheme == "slow":
                # Simulate a slow resource
                await anyio.sleep(2.0)
                return f"Slow response from {uri.host}"

            raise McpError(
                error=ErrorData(
                    code=404, message="OOPS! no resource with that URI was found"
                )
            )

        @self.list_tools()
        async def handle_list_tools() -> list[Tool]:
            return [
                Tool(
                    name="test_tool",
                    description="A test tool",
                    inputSchema={"type": "object", "properties": {}},
                )
            ]

        @self.call_tool()
        async def handle_call_tool(name: str, args: dict) -> list[TextContent]:
            return [TextContent(type="text", text=f"Called {name}")]


# Test fixtures
def make_server_app() -> Starlette:
    """Create test Starlette app with WebSocket transport"""
    server = ServerTest()

    async def handle_ws(websocket):
        async with websocket_server(
            websocket.scope, websocket.receive, websocket.send
        ) as streams:
            await server.run(
                streams[0], streams[1], server.create_initialization_options()
            )

    app = Starlette(
        routes=[
            WebSocketRoute("/ws", endpoint=handle_ws),
        ]
    )

    return app


def run_server(server_port: int) -> None:
    app = make_server_app()
    server = uvicorn.Server(
        config=uvicorn.Config(
            app=app, host="127.0.0.1", port=server_port, log_level="error"
        )
    )
    print(f"starting server on {server_port}")
    server.run()

    # Give server time to start
    while not server.started:
        print("waiting for server to start")
        time.sleep(0.5)


@pytest.fixture()
def server(server_port: int) -> Generator[None, None, None]:
    proc = multiprocessing.Process(
        target=run_server, kwargs={"server_port": server_port}, daemon=True
    )
    print("starting process")
    proc.start()

    # Wait for server to be running
    max_attempts = 20
    attempt = 0
    print("waiting for server to start")
    while attempt < max_attempts:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", server_port))
                break
        except ConnectionRefusedError:
            time.sleep(0.1)
            attempt += 1
    else:
        raise RuntimeError(f"Server failed to start after {max_attempts} attempts")

    yield

    print("killing server")
    # Signal the server to stop
    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():
        print("server process failed to terminate")


@pytest.fixture()
async def initialized_ws_client_session(
    server, server_url: str
) -> AsyncGenerator[ClientSession, None]:
    """Create and initialize a WebSocket client session"""
    async with websocket_client(server_url + "/ws") as streams:
        async with ClientSession(*streams) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == SERVER_NAME

            # Test ping
            ping_result = await session.send_ping()
            assert isinstance(ping_result, EmptyResult)

            yield session


# Tests
@pytest.mark.anyio
async def test_ws_client_basic_connection(server: None, server_url: str) -> None:
    """Test the WebSocket connection establishment"""
    async with websocket_client(server_url + "/ws") as streams:
        async with ClientSession(*streams) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == SERVER_NAME

            # Test ping
            ping_result = await session.send_ping()
            assert isinstance(ping_result, EmptyResult)


@pytest.mark.anyio
async def test_ws_client_happy_request_and_response(
    initialized_ws_client_session: ClientSession,
) -> None:
    """Test a successful request and response via WebSocket"""
    result = await initialized_ws_client_session.read_resource(
        AnyUrl("foobar://example")
    )
    assert isinstance(result, ReadResourceResult)
    assert isinstance(result.contents, list)
    assert len(result.contents) > 0
    assert isinstance(result.contents[0], TextResourceContents)
    assert result.contents[0].text == "Read example"


@pytest.mark.anyio
async def test_ws_client_exception_handling(
    initialized_ws_client_session: ClientSession,
) -> None:
    """Test exception handling in WebSocket communication"""
    with pytest.raises(McpError) as exc_info:
        await initialized_ws_client_session.read_resource(AnyUrl("unknown://example"))
    assert exc_info.value.error.code == 404


@pytest.mark.anyio
async def test_ws_client_timeout(
    initialized_ws_client_session: ClientSession,
) -> None:
    """Test timeout handling in WebSocket communication"""
    # Set a very short timeout to trigger a timeout exception
    with pytest.raises(TimeoutError):
        with anyio.fail_after(0.1):  # 100ms timeout
            await initialized_ws_client_session.read_resource(AnyUrl("slow://example"))

    # Now test that we can still use the session after a timeout
    with anyio.fail_after(5):  # Longer timeout to allow completion
        result = await initialized_ws_client_session.read_resource(
            AnyUrl("foobar://example")
        )
        assert isinstance(result, ReadResourceResult)
        assert isinstance(result.contents, list)
        assert len(result.contents) > 0
        assert isinstance(result.contents[0], TextResourceContents)
        assert result.contents[0].text == "Read example"
