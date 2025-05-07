"""
Integration tests for FastMCP server functionality.

These tests validate the proper functioning of FastMCP in various configurations,
including with and without authentication.
"""

import multiprocessing
import socket
import time
from collections.abc import Generator

import pytest
import uvicorn

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP
from mcp.types import InitializeResult, TextContent


@pytest.fixture
def server_port() -> int:
    """Get a free port for testing."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server_url(server_port: int) -> str:
    """Get the server URL for testing."""
    return f"http://127.0.0.1:{server_port}"


@pytest.fixture
def http_server_port() -> int:
    """Get a free port for testing the StreamableHTTP server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def http_server_url(http_server_port: int) -> str:
    """Get the StreamableHTTP server URL for testing."""
    return f"http://127.0.0.1:{http_server_port}"


@pytest.fixture
def stateless_http_server_port() -> int:
    """Get a free port for testing the stateless StreamableHTTP server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def stateless_http_server_url(stateless_http_server_port: int) -> str:
    """Get the stateless StreamableHTTP server URL for testing."""
    return f"http://127.0.0.1:{stateless_http_server_port}"


# Create a function to make the FastMCP server app
def make_fastmcp_app():
    """Create a FastMCP server without auth settings."""
    from starlette.applications import Starlette

    mcp = FastMCP(name="NoAuthServer")

    # Add a simple tool
    @mcp.tool(description="A simple echo tool")
    def echo(message: str) -> str:
        return f"Echo: {message}"

    # Create the SSE app
    app: Starlette = mcp.sse_app()

    return mcp, app


def make_fastmcp_streamable_http_app():
    """Create a FastMCP server with StreamableHTTP transport."""
    from starlette.applications import Starlette

    mcp = FastMCP(name="NoAuthServer")

    # Add a simple tool
    @mcp.tool(description="A simple echo tool")
    def echo(message: str) -> str:
        return f"Echo: {message}"

    # Create the StreamableHTTP app
    app: Starlette = mcp.streamable_http_app()

    return mcp, app


def make_fastmcp_stateless_http_app():
    """Create a FastMCP server with stateless StreamableHTTP transport."""
    from starlette.applications import Starlette

    mcp = FastMCP(name="StatelessServer", stateless_http=True)

    # Add a simple tool
    @mcp.tool(description="A simple echo tool")
    def echo(message: str) -> str:
        return f"Echo: {message}"

    # Create the StreamableHTTP app
    app: Starlette = mcp.streamable_http_app()

    return mcp, app


def run_server(server_port: int) -> None:
    """Run the server."""
    _, app = make_fastmcp_app()
    server = uvicorn.Server(
        config=uvicorn.Config(
            app=app, host="127.0.0.1", port=server_port, log_level="error"
        )
    )
    print(f"Starting server on port {server_port}")
    server.run()


def run_streamable_http_server(server_port: int) -> None:
    """Run the StreamableHTTP server."""
    _, app = make_fastmcp_streamable_http_app()
    server = uvicorn.Server(
        config=uvicorn.Config(
            app=app, host="127.0.0.1", port=server_port, log_level="error"
        )
    )
    print(f"Starting StreamableHTTP server on port {server_port}")
    server.run()


def run_stateless_http_server(server_port: int) -> None:
    """Run the stateless StreamableHTTP server."""
    _, app = make_fastmcp_stateless_http_app()
    server = uvicorn.Server(
        config=uvicorn.Config(
            app=app, host="127.0.0.1", port=server_port, log_level="error"
        )
    )
    print(f"Starting stateless StreamableHTTP server on port {server_port}")
    server.run()


@pytest.fixture()
def server(server_port: int) -> Generator[None, None, None]:
    """Start the server in a separate process and clean up after the test."""
    proc = multiprocessing.Process(target=run_server, args=(server_port,), daemon=True)
    print("Starting server process")
    proc.start()

    # Wait for server to be running
    max_attempts = 20
    attempt = 0
    print("Waiting for server to start")
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

    print("Killing server")
    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():
        print("Server process failed to terminate")


@pytest.fixture()
def streamable_http_server(http_server_port: int) -> Generator[None, None, None]:
    """Start the StreamableHTTP server in a separate process."""
    proc = multiprocessing.Process(
        target=run_streamable_http_server, args=(http_server_port,), daemon=True
    )
    print("Starting StreamableHTTP server process")
    proc.start()

    # Wait for server to be running
    max_attempts = 20
    attempt = 0
    print("Waiting for StreamableHTTP server to start")
    while attempt < max_attempts:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", http_server_port))
                break
        except ConnectionRefusedError:
            time.sleep(0.1)
            attempt += 1
    else:
        raise RuntimeError(
            f"StreamableHTTP server failed to start after {max_attempts} attempts"
        )

    yield

    print("Killing StreamableHTTP server")
    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():
        print("StreamableHTTP server process failed to terminate")


@pytest.fixture()
def stateless_http_server(
    stateless_http_server_port: int,
) -> Generator[None, None, None]:
    """Start the stateless StreamableHTTP server in a separate process."""
    proc = multiprocessing.Process(
        target=run_stateless_http_server,
        args=(stateless_http_server_port,),
        daemon=True,
    )
    print("Starting stateless StreamableHTTP server process")
    proc.start()

    # Wait for server to be running
    max_attempts = 20
    attempt = 0
    print("Waiting for stateless StreamableHTTP server to start")
    while attempt < max_attempts:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", stateless_http_server_port))
                break
        except ConnectionRefusedError:
            time.sleep(0.1)
            attempt += 1
    else:
        raise RuntimeError(
            f"Stateless server failed to start after {max_attempts} attempts"
        )

    yield

    print("Killing stateless StreamableHTTP server")
    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():
        print("Stateless StreamableHTTP server process failed to terminate")


@pytest.mark.anyio
async def test_fastmcp_without_auth(server: None, server_url: str) -> None:
    """Test that FastMCP works when auth settings are not provided."""
    # Connect to the server
    async with sse_client(server_url + "/sse") as streams:
        async with ClientSession(*streams) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "NoAuthServer"

            # Test that we can call tools without authentication
            tool_result = await session.call_tool("echo", {"message": "hello"})
            assert len(tool_result.content) == 1
            assert isinstance(tool_result.content[0], TextContent)
            assert tool_result.content[0].text == "Echo: hello"


@pytest.mark.anyio
async def test_fastmcp_streamable_http(
    streamable_http_server: None, http_server_url: str
) -> None:
    """Test that FastMCP works with StreamableHTTP transport."""
    # Connect to the server using StreamableHTTP
    async with streamablehttp_client(http_server_url + "/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        # Create a session using the client streams
        async with ClientSession(read_stream, write_stream) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "NoAuthServer"

            # Test that we can call tools without authentication
            tool_result = await session.call_tool("echo", {"message": "hello"})
            assert len(tool_result.content) == 1
            assert isinstance(tool_result.content[0], TextContent)
            assert tool_result.content[0].text == "Echo: hello"


@pytest.mark.anyio
async def test_fastmcp_stateless_streamable_http(
    stateless_http_server: None, stateless_http_server_url: str
) -> None:
    """Test that FastMCP works with stateless StreamableHTTP transport."""
    # Connect to the server using StreamableHTTP
    async with streamablehttp_client(stateless_http_server_url + "/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "StatelessServer"
            tool_result = await session.call_tool("echo", {"message": "hello"})
            assert len(tool_result.content) == 1
            assert isinstance(tool_result.content[0], TextContent)
            assert tool_result.content[0].text == "Echo: hello"

            for i in range(3):
                tool_result = await session.call_tool("echo", {"message": f"test_{i}"})
                assert len(tool_result.content) == 1
                assert isinstance(tool_result.content[0], TextContent)
                assert tool_result.content[0].text == f"Echo: test_{i}"
