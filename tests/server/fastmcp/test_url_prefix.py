import multiprocessing
import socket
import time
from typing import AsyncGenerator, Generator

import anyio
import httpx
import pytest
import uvicorn
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.routing import Mount, Route

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from mcp.types import (
    InitializeResult,
    TextContent,
)

# Test server implementation
class MockFastMCPServer(FastMCP):
    def __init__(self, url_prefix: str = ""):
        super().__init__(name="test_url_prefix_server", url_prefix=url_prefix)
        
        @self.tool()
        def test_tool() -> str:
            return "Test tool response"


def make_server_app(url_prefix: str = "") -> Starlette:
    """Create test Starlette app with SSE transport and url_prefix"""
    server = MockFastMCPServer(url_prefix=url_prefix)
    sse = SseServerTransport(f"{url_prefix}/messages/")
    
    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server._mcp_server.run(
                streams[0], streams[1], server._mcp_server.create_initialization_options()
            )
    
    app = Starlette(
        routes=[
            Route(f"{url_prefix}/sse", endpoint=handle_sse),
            Mount(f"{url_prefix}/messages/", app=sse.handle_post_message),
        ]
    )
    
    return app


@pytest.fixture
def server_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server_url(server_port: int) -> str:
    return f"http://127.0.0.1:{server_port}"


class ServerRunner:
    """Class to manage running servers with different prefixes"""
    def __init__(self, server_port: int, url_prefix: str = ""):
        self.server_port = server_port
        self.url_prefix = url_prefix
        self.process = None
    
    def start(self):
        """Start the server in a separate process"""
        self.process = multiprocessing.Process(
            target=self._run_server,
            kwargs={"server_port": self.server_port, "url_prefix": self.url_prefix},
            daemon=True
        )
        self.process.start()
        
        # Wait for server to be running
        max_attempts = 20
        attempt = 0
        while attempt < max_attempts:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect(("127.0.0.1", self.server_port))
                    break
            except ConnectionRefusedError:
                time.sleep(0.1)
                attempt += 1
        else:
            raise RuntimeError(
                f"Server failed to start after {max_attempts} attempts"
            )
    
    def stop(self):
        """Stop the server process"""
        if self.process and self.process.is_alive():
            self.process.kill()
            self.process.join(timeout=2)
    
    @staticmethod
    def _run_server(server_port: int, url_prefix: str = ""):
        """Run the server with the given url_prefix"""
        app = make_server_app(url_prefix=url_prefix)
        server = uvicorn.Server(
            config=uvicorn.Config(
                app=app, host="127.0.0.1", port=server_port, log_level="error"
            )
        )
        server.run()


@pytest.fixture
def empty_prefix_server(server_port: int) -> Generator[ServerRunner, None, None]:
    """Server with empty prefix"""
    runner = ServerRunner(server_port, url_prefix="")
    runner.start()
    yield runner
    runner.stop()


@pytest.fixture
def simple_prefix_server(server_port: int) -> Generator[ServerRunner, None, None]:
    """Server with a simple prefix"""
    runner = ServerRunner(server_port, url_prefix="/api")
    runner.start()
    yield runner
    runner.stop()


@pytest.fixture
def complex_prefix_server(server_port: int) -> Generator[ServerRunner, None, None]:
    """Server with a complex prefix"""
    runner = ServerRunner(server_port, url_prefix="/api/v1")
    runner.start()
    yield runner
    runner.stop()


@pytest.fixture
async def http_client(server_url) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create test client"""
    async with httpx.AsyncClient(base_url=server_url) as client:
        yield client


# Tests
@pytest.mark.anyio
async def test_empty_prefix(empty_prefix_server, server_url):
    """Test that the server works with an empty prefix"""
    # Connect to server with empty prefix
    async with sse_client(f"{server_url}/sse") as streams:
        async with ClientSession(*streams) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "test_url_prefix_server"
            
            # Test tool call
            result = await session.call_tool("test_tool", {})
            assert len(result.content) == 1
            assert isinstance(result.content[0], TextContent)
            assert result.content[0].text == "Test tool response"


@pytest.mark.anyio
async def test_simple_prefix(simple_prefix_server, server_url):
    """Test that the server works with a simple prefix"""
    # Connect to server with simple prefix
    prefix = "/api"
    async with sse_client(f"{server_url}{prefix}/sse") as streams:
        async with ClientSession(*streams) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "test_url_prefix_server"
            
            # Test tool call
            result = await session.call_tool("test_tool", {})
            assert len(result.content) == 1
            assert isinstance(result.content[0], TextContent)
            assert result.content[0].text == "Test tool response"


@pytest.mark.anyio
async def test_complex_prefix(complex_prefix_server, server_url):
    """Test that the server works with a complex prefix"""
    # Connect to server with complex prefix
    prefix = "/api/v1"
    async with sse_client(f"{server_url}{prefix}/sse") as streams:
        async with ClientSession(*streams) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "test_url_prefix_server"
            
            # Test tool call
            result = await session.call_tool("test_tool", {})
            assert len(result.content) == 1
            assert isinstance(result.content[0], TextContent)
            assert result.content[0].text == "Test tool response"


@pytest.mark.anyio
async def test_raw_connection_with_prefix(simple_prefix_server, http_client):
    """Test the raw HTTP connection with a prefix"""
    prefix = "/api"
    async with anyio.create_task_group():
        async def connection_test() -> None:
            async with http_client.stream("GET", f"{prefix}/sse") as response:
                assert response.status_code == 200
                assert (
                    response.headers["content-type"]
                    == "text/event-stream; charset=utf-8"
                )

                line_number = 0
                async for line in response.aiter_lines():
                    if line_number == 0:
                        assert line == "event: endpoint"
                    elif line_number == 1:
                        assert line.startswith(f"data: {prefix}/messages/?session_id=")
                    else:
                        return
                    line_number += 1

        # Add timeout to prevent test from hanging if it fails
        with anyio.fail_after(3):
            await connection_test()


@pytest.mark.anyio
async def test_invalid_connection_without_prefix(simple_prefix_server, http_client):
    """Test that connecting without the prefix fails"""
    try:
        # This should fail because the endpoint is at /api/sse, not /sse
        async with http_client.stream("GET", "/sse") as response:
            assert response.status_code == 404
    except httpx.HTTPError:
        # Either a 404 response or a connection error is acceptable
        pass


@pytest.mark.anyio
async def test_fastmcp_run_sse_async_routes():
    """Test that FastMCP correctly sets up the routes with url_prefix during run_sse_async"""
    from unittest.mock import AsyncMock, patch
    
    # Test with empty prefix
    mcp1 = FastMCP(name="test_server")
    with patch("uvicorn.Server.serve", new_callable=AsyncMock) as mock_serve:
        with patch("starlette.applications.Starlette") as mock_starlette:
            await mcp1.run_sse_async()
            # Verify routes were created with empty prefix
            routes_call = mock_starlette.call_args[1]['routes']
            # There should be two routes - one for SSE and one for message handling
            assert len(routes_call) == 2
            # First route should be for /sse
            assert routes_call[0].path == "/sse"
            # Second route should be Mount for /messages
            assert routes_call[1].path == "/messages"
    
    # Test with simple prefix
    mcp2 = FastMCP(name="test_server", url_prefix="/api")
    with patch("uvicorn.Server.serve", new_callable=AsyncMock) as mock_serve:
        with patch("starlette.applications.Starlette") as mock_starlette:
            await mcp2.run_sse_async()
            # Verify routes were created with simple prefix
            routes_call = mock_starlette.call_args[1]['routes']
            # There should be two routes - one for SSE and one for message handling
            assert len(routes_call) == 2
            # First route should be for /api/sse
            assert routes_call[0].path == "/api/sse"
            # Second route should be Mount for /api/messages
            assert routes_call[1].path == "/api/messages"
    
    # Test with complex prefix
    mcp3 = FastMCP(name="test_server", url_prefix="/api/v1/my_mcp_server")
    with patch("uvicorn.Server.serve", new_callable=AsyncMock) as mock_serve:
        with patch("starlette.applications.Starlette") as mock_starlette:
            await mcp3.run_sse_async()
            # Verify routes were created with complex prefix
            routes_call = mock_starlette.call_args[1]['routes']
            # There should be two routes - one for SSE and one for message handling
            assert len(routes_call) == 2
            # First route should be for /api/v1/my_mcp_server/sse
            assert routes_call[0].path == "/api/v1/my_mcp_server/sse"
            # Second route should be Mount for /api/v1/my_mcp_server/messages
            assert routes_call[1].path == "/api/v1/my_mcp_server/messages"
