"""
Tests for the StreamableHTTP server transport validation.

This file contains tests for request validation in the StreamableHTTP transport.
"""

import socket
import time
from collections.abc import Generator
from multiprocessing import Process

import anyio
import pytest
import requests
import uvicorn
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from mcp.server.streamableHttp import (
    MCP_SESSION_ID_HEADER,
    StreamableHTTPServerTransport,
)
from mcp.types import JSONRPCMessage

# Test constants
SERVER_NAME = "test_streamable_http_server"
TEST_SESSION_ID = "test-session-id-12345"


# App handler class for testing validation (not a pytest test class)
class StreamableAppHandler:
    def __init__(self, session_id=None):
        self.transport = StreamableHTTPServerTransport(mcp_session_id=session_id)
        self.started = False
        self.read_stream = None
        self.write_stream = None

    async def startup(self):
        """Initialize the transport streams."""
        # Create real memory streams to satisfy type checking
        read_stream_writer, read_stream = anyio.create_memory_object_stream[
            JSONRPCMessage | Exception
        ](0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream[
            JSONRPCMessage
        ](0)

        # Assign the streams to the transport
        self.transport._read_stream_writer = read_stream_writer
        self.transport._write_stream_reader = write_stream_reader

        # Store the streams so they don't get garbage collected
        self.read_stream = read_stream
        self.write_stream = write_stream

        self.started = True
        print("Transport streams initialized")

    async def handle_request(self, request: Request):
        """Handle incoming requests by validating and responding."""
        # Make sure transport is initialized
        if not self.started:
            await self.startup()

        # Let the transport handle the request validation and response
        try:
            await self.transport.handle_request(
                request.scope, request.receive, request._send
            )
        except Exception as e:
            print(f"Error handling request: {e}")
            # Make sure we provide an error response
            response = Response(
                status_code=500,
                content=f"Server error: {str(e)}",
                media_type="text/plain",
            )
            await response(request.scope, request.receive, request._send)


@pytest.fixture
def server_port() -> int:
    """Find an available port for the test server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server_url(server_port: int) -> str:
    """Get the URL for the test server."""
    return f"http://127.0.0.1:{server_port}"


def create_app(session_id=None) -> Starlette:
    """Create a Starlette application for testing."""
    # Create our test app handler
    app_handler = StreamableAppHandler(session_id=session_id)

    # Define a startup event to ensure the transport is initialized
    async def on_startup():
        """Initialize the transport on application startup."""
        print("Initializing transport streams...")
        await app_handler.startup()
        app_handler.started = True
        print("Transport initialized")

    app = Starlette(
        debug=True,  # Enable debug mode for better error messages
        routes=[
            Route(
                "/mcp",
                endpoint=app_handler.handle_request,
                methods=["GET", "POST", "DELETE"],
            ),
        ],
        on_startup=[on_startup],
    )

    return app


def run_server(port: int, session_id=None) -> None:
    """Run the test server."""
    print(f"Starting test server on port {port} with session_id={session_id}")

    # Create app with simpler configuration
    app = create_app(session_id)

    # Configure to use a single worker and simpler settings
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="info",  # Use info to see startup messages
        limit_concurrency=10,
        timeout_keep_alive=2,
        access_log=False,
    )

    # Start the server
    server = uvicorn.Server(config=config)

    # This is important to catch exceptions and prevent test hangs
    try:
        print("Server starting...")
        server.run()
    except Exception as e:
        print(f"ERROR: Server failed to run: {e}")
        import traceback

        traceback.print_exc()

    print("Server shutdown")


@pytest.fixture
def basic_server(server_port: int) -> Generator[None, None, None]:
    """Start a basic server without session ID."""
    # Start server process
    process = Process(target=run_server, kwargs={"port": server_port}, daemon=True)
    process.start()

    # Wait for server to start
    max_attempts = 20
    attempt = 0
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

    # Clean up
    process.terminate()
    process.join(timeout=1)
    if process.is_alive():
        process.kill()


@pytest.fixture
def session_server(server_port: int) -> Generator[str, None, None]:
    """Start a server with session ID."""
    # Start server process
    process = Process(
        target=run_server,
        kwargs={"port": server_port, "session_id": TEST_SESSION_ID},
        daemon=True,
    )
    process.start()

    # Wait for server to start
    max_attempts = 20
    attempt = 0
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

    yield TEST_SESSION_ID

    # Clean up
    process.terminate()
    process.join(timeout=1)
    if process.is_alive():
        process.kill()


# Basic request validation tests
def test_accept_header_validation(basic_server, server_url):
    """Test that Accept header is properly validated."""
    # Test without Accept header
    response = requests.post(
        f"{server_url}/mcp",
        headers={"Content-Type": "application/json"},
        json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
    )
    assert response.status_code == 406
    assert "Not Acceptable" in response.text

    # Test with only application/json
    response = requests.post(
        f"{server_url}/mcp",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
    )
    assert response.status_code == 406

    # Test with only text/event-stream
    response = requests.post(
        f"{server_url}/mcp",
        headers={"Accept": "text/event-stream", "Content-Type": "application/json"},
        json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
    )
    assert response.status_code == 406


def test_content_type_validation(basic_server, server_url):
    """Test that Content-Type header is properly validated."""
    # Test with incorrect Content-Type
    response = requests.post(
        f"{server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "text/plain",
        },
        data="This is not JSON",
    )
    assert response.status_code == 415
    assert "Unsupported Media Type" in response.text


def test_json_validation(basic_server, server_url):
    """Test that JSON content is properly validated."""
    # Test with invalid JSON
    response = requests.post(
        f"{server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        data="this is not valid json",
    )
    assert response.status_code == 400
    assert "Parse error" in response.text

    # Test with valid JSON but invalid JSON-RPC
    response = requests.post(
        f"{server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"foo": "bar"},
    )
    assert response.status_code == 400
    assert "Validation error" in response.text


def test_method_not_allowed(basic_server, server_url):
    """Test that unsupported HTTP methods are rejected."""
    # Test with unsupported method (PUT)
    response = requests.put(
        f"{server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
    )
    assert response.status_code == 405
    assert "Method Not Allowed" in response.text


def test_get_request_validation(basic_server, server_url):
    """Test GET request validation for SSE streams."""
    # Test GET without Accept header
    response = requests.get(f"{server_url}/mcp")
    assert response.status_code == 406
    assert "Not Acceptable" in response.text

    # Test GET with wrong Accept header
    response = requests.get(
        f"{server_url}/mcp",
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 406


def test_session_validation(session_server, server_url):
    """Test session ID validation."""
    # session_id not used directly in this test

    # Test without session ID
    response = requests.post(
        f"{server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"jsonrpc": "2.0", "method": "list_tools", "id": 1},
    )
    assert response.status_code == 400
    assert "Missing session ID" in response.text

    # Test with invalid session ID
    response = requests.post(
        f"{server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            MCP_SESSION_ID_HEADER: "invalid-session-id",
        },
        json={"jsonrpc": "2.0", "method": "list_tools", "id": 1},
    )
    assert response.status_code == 404
    assert "Invalid or expired session ID" in response.text


def test_delete_request(session_server, server_url):
    """Test DELETE request for session termination."""
    # session_id not used directly in this test

    # Test without session ID
    response = requests.delete(f"{server_url}/mcp")
    assert response.status_code == 400
    assert "Missing session ID" in response.text

    # Test with invalid session ID
    response = requests.delete(
        f"{server_url}/mcp",
        headers={MCP_SESSION_ID_HEADER: "invalid-session-id"},
    )
    assert response.status_code == 404
    assert "Invalid or expired session ID" in response.text


def test_delete_without_session_support(basic_server, server_url):
    """Test DELETE request when server doesn't support sessions."""
    # Server without session support should reject DELETE
    response = requests.delete(f"{server_url}/mcp")
    assert response.status_code == 405
    assert "Method Not Allowed" in response.text
