"""
Tests for the StreamableHTTP server transport validation.

This file contains tests for request validation in the StreamableHTTP transport.
"""

import contextlib
import multiprocessing
import socket
import time
from collections.abc import Generator
from http import HTTPStatus
from uuid import uuid4

import anyio
import pytest
import requests
import uvicorn
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount

from mcp.server import Server
from mcp.server.streamableHttp import (
    MCP_SESSION_ID_HEADER,
    SESSION_ID_PATTERN,
    StreamableHTTPServerTransport,
)
from mcp.shared.exceptions import McpError
from mcp.types import (
    ErrorData,
    TextContent,
    Tool,
)

# Test constants
SERVER_NAME = "test_streamable_http_server"
TEST_SESSION_ID = "test-session-id-12345"
INIT_REQUEST = {
    "jsonrpc": "2.0",
    "method": "initialize",
    "params": {
        "clientInfo": {"name": "test-client", "version": "1.0"},
        "protocolVersion": "2025-03-26",
        "capabilities": {},
    },
    "id": "init-1",
}


# Test server implementation that follows MCP protocol
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


def create_app(is_json_response_enabled=False) -> Starlette:
    """Create a Starlette application for testing that matches the example server.

    Args:
        is_json_response_enabled: If True, use JSON responses instead of SSE streams.
    """
    # Create server instance
    server = ServerTest()

    server_instances = {}
    # Lock to prevent race conditions when creating new sessions
    session_creation_lock = anyio.Lock()
    task_group = None

    @contextlib.asynccontextmanager
    async def lifespan(app):
        """Application lifespan context manager for managing task group."""
        nonlocal task_group

        async with anyio.create_task_group() as tg:
            task_group = tg
            print("Application started, task group initialized!")
            try:
                yield
            finally:
                print("Application shutting down, cleaning up resources...")
                if task_group:
                    tg.cancel_scope.cancel()
                    task_group = None
                print("Resources cleaned up successfully.")

    async def handle_streamable_http(scope, receive, send):
        request = Request(scope, receive)
        request_mcp_session_id = request.headers.get(MCP_SESSION_ID_HEADER)

        # Use existing transport if session ID matches
        if (
            request_mcp_session_id is not None
            and request_mcp_session_id in server_instances
        ):
            transport = server_instances[request_mcp_session_id]

            await transport.handle_request(scope, receive, send)
        elif request_mcp_session_id is None:
            async with session_creation_lock:
                new_session_id = uuid4().hex

                http_transport = StreamableHTTPServerTransport(
                    mcp_session_id=new_session_id,
                    is_json_response_enabled=is_json_response_enabled,
                )

                async with http_transport.connect() as streams:
                    read_stream, write_stream = streams

                    async def run_server():
                        try:
                            await server.run(
                                read_stream,
                                write_stream,
                                server.create_initialization_options(),
                            )
                        except Exception as e:
                            print(f"Server exception: {e}")

                    if task_group is None:
                        response = Response(
                            "Internal Server Error: Task group is not initialized",
                            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                        )
                        await response(scope, receive, send)
                        return

                    # Store the instance before starting the task to prevent races
                    server_instances[http_transport.mcp_session_id] = http_transport
                    task_group.start_soon(run_server)

                    await http_transport.handle_request(scope, receive, send)
        else:
            response = Response(
                "Bad Request: No valid session ID provided",
                status_code=HTTPStatus.BAD_REQUEST,
            )
            await response(scope, receive, send)

    # Create an ASGI application
    app = Starlette(
        debug=True,
        routes=[
            Mount("/mcp", app=handle_streamable_http),
        ],
        lifespan=lifespan,
    )

    return app


def run_server(port: int, is_json_response_enabled=False) -> None:
    """Run the test server.

    Args:
        port: Port to listen on.
        is_json_response_enabled: If True, use JSON responses instead of SSE streams.
    """
    print(
        f"Starting test server on port {port} with "
        f"json_enabled={is_json_response_enabled}"
    )

    app = create_app(is_json_response_enabled)
    # Configure server
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        limit_concurrency=10,
        timeout_keep_alive=5,
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


# Test fixtures - using same approach as SSE tests
@pytest.fixture
def basic_server_port() -> int:
    """Find an available port for the basic server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def json_server_port() -> int:
    """Find an available port for the JSON response server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def basic_server(basic_server_port: int) -> Generator[None, None, None]:
    """Start a basic server."""
    proc = multiprocessing.Process(
        target=run_server, kwargs={"port": basic_server_port}, daemon=True
    )
    proc.start()

    # Wait for server to be running
    max_attempts = 20
    attempt = 0
    while attempt < max_attempts:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", basic_server_port))
                break
        except ConnectionRefusedError:
            time.sleep(0.1)
            attempt += 1
    else:
        raise RuntimeError(f"Server failed to start after {max_attempts} attempts")

    yield

    # Clean up
    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():
        print("server process failed to terminate")


@pytest.fixture
def json_response_server(json_server_port: int) -> Generator[None, None, None]:
    """Start a server with JSON response enabled."""
    proc = multiprocessing.Process(
        target=run_server,
        kwargs={"port": json_server_port, "is_json_response_enabled": True},
        daemon=True,
    )
    proc.start()

    # Wait for server to be running
    max_attempts = 20
    attempt = 0
    while attempt < max_attempts:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", json_server_port))
                break
        except ConnectionRefusedError:
            time.sleep(0.1)
            attempt += 1
    else:
        raise RuntimeError(f"Server failed to start after {max_attempts} attempts")

    yield

    # Clean up
    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():
        print("server process failed to terminate")


@pytest.fixture
def basic_server_url(basic_server_port: int) -> str:
    """Get the URL for the basic test server."""
    return f"http://127.0.0.1:{basic_server_port}"


@pytest.fixture
def json_server_url(json_server_port: int) -> str:
    """Get the URL for the JSON response test server."""
    return f"http://127.0.0.1:{json_server_port}"


# Basic request validation tests
def test_accept_header_validation(basic_server, basic_server_url):
    """Test that Accept header is properly validated."""
    # Test without Accept header
    response = requests.post(
        f"{basic_server_url}/mcp",
        headers={"Content-Type": "application/json"},
        json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
    )
    assert response.status_code == 406
    assert "Not Acceptable" in response.text


def test_content_type_validation(basic_server, basic_server_url):
    """Test that Content-Type header is properly validated."""
    # Test with incorrect Content-Type
    response = requests.post(
        f"{basic_server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "text/plain",
        },
        data="This is not JSON",
    )
    assert response.status_code == 415
    assert "Unsupported Media Type" in response.text


def test_json_validation(basic_server, basic_server_url):
    """Test that JSON content is properly validated."""
    # Test with invalid JSON
    response = requests.post(
        f"{basic_server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        data="this is not valid json",
    )
    assert response.status_code == 400
    assert "Parse error" in response.text


def test_json_parsing(basic_server, basic_server_url):
    """Test that JSON content is properly parse."""
    # Test with valid JSON but invalid JSON-RPC
    response = requests.post(
        f"{basic_server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"foo": "bar"},
    )
    assert response.status_code == 400
    assert "Validation error" in response.text


def test_method_not_allowed(basic_server, basic_server_url):
    """Test that unsupported HTTP methods are rejected."""
    # Test with unsupported method (PUT)
    response = requests.put(
        f"{basic_server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
    )
    assert response.status_code == 405
    assert "Method Not Allowed" in response.text


def test_session_validation(basic_server, basic_server_url):
    """Test session ID validation."""
    # session_id not used directly in this test

    # Test without session ID
    response = requests.post(
        f"{basic_server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"jsonrpc": "2.0", "method": "list_tools", "id": 1},
    )
    assert response.status_code == 400
    assert "Missing session ID" in response.text


def test_session_id_pattern():
    """Test that SESSION_ID_PATTERN correctly validates session IDs."""
    # Valid session IDs (visible ASCII characters from 0x21 to 0x7E)
    valid_session_ids = [
        "test-session-id",
        "1234567890",
        "session!@#$%^&*()_+-=[]{}|;:,.<>?/",
        "~`",
    ]

    for session_id in valid_session_ids:
        assert SESSION_ID_PATTERN.match(session_id) is not None
        # Ensure fullmatch matches too (whole string)
        assert SESSION_ID_PATTERN.fullmatch(session_id) is not None

    # Invalid session IDs
    invalid_session_ids = [
        "",  # Empty string
        " test",  # Space (0x20)
        "test\t",  # Tab
        "test\n",  # Newline
        "test\r",  # Carriage return
        "test" + chr(0x7F),  # DEL character
        "test" + chr(0x80),  # Extended ASCII
        "test" + chr(0x00),  # Null character
        "test" + chr(0x20),  # Space (0x20)
    ]

    for session_id in invalid_session_ids:
        # For invalid IDs, either match will fail or fullmatch will fail
        if SESSION_ID_PATTERN.match(session_id) is not None:
            # If match succeeds, fullmatch should fail (partial match case)
            assert SESSION_ID_PATTERN.fullmatch(session_id) is None


def test_streamable_http_transport_init_validation():
    """Test that StreamableHTTPServerTransport validates session ID on init."""
    # Valid session ID should initialize without errors
    valid_transport = StreamableHTTPServerTransport(mcp_session_id="valid-id")
    assert valid_transport.mcp_session_id == "valid-id"

    # None should be accepted
    none_transport = StreamableHTTPServerTransport(mcp_session_id=None)
    assert none_transport.mcp_session_id is None

    # Invalid session ID should raise ValueError
    with pytest.raises(ValueError) as excinfo:
        StreamableHTTPServerTransport(mcp_session_id="invalid id with space")
    assert "Session ID must only contain visible ASCII characters" in str(excinfo.value)

    # Test with control characters
    with pytest.raises(ValueError):
        StreamableHTTPServerTransport(mcp_session_id="test\nid")

    with pytest.raises(ValueError):
        StreamableHTTPServerTransport(mcp_session_id="test\n")


def test_session_termination(basic_server, basic_server_url):
    """Test session termination via DELETE and subsequent request handling."""
    response = requests.post(
        f"{basic_server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json=INIT_REQUEST,
    )
    assert response.status_code == 200

    # Now terminate the session
    session_id = response.headers.get(MCP_SESSION_ID_HEADER)
    response = requests.delete(
        f"{basic_server_url}/mcp",
        headers={MCP_SESSION_ID_HEADER: session_id},
    )
    assert response.status_code == 200

    # Try to use the terminated session
    response = requests.post(
        f"{basic_server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            MCP_SESSION_ID_HEADER: session_id,
        },
        json={"jsonrpc": "2.0", "method": "ping", "id": 2},
    )
    assert response.status_code == 404
    assert "Session has been terminated" in response.text


def test_response(basic_server, basic_server_url):
    """Test response handling for a valid request."""
    mcp_url = f"{basic_server_url}/mcp"
    response = requests.post(
        mcp_url,
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json=INIT_REQUEST,
    )
    assert response.status_code == 200

    # Now terminate the session
    session_id = response.headers.get(MCP_SESSION_ID_HEADER)

    # Try to use the terminated session
    tools_response = requests.post(
        mcp_url,
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            MCP_SESSION_ID_HEADER: session_id,  # Use the session ID we got earlier
        },
        json={"jsonrpc": "2.0", "method": "tools/list", "id": "tools-1"},
        stream=True,
    )
    assert tools_response.status_code == 200
    assert tools_response.headers.get("Content-Type") == "text/event-stream"


def test_json_response(json_response_server, json_server_url):
    """Test response handling when is_json_response_enabled is True."""
    mcp_url = f"{json_server_url}/mcp"
    response = requests.post(
        mcp_url,
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json=INIT_REQUEST,
    )
    assert response.status_code == 200
    assert response.headers.get("Content-Type") == "application/json"


def test_get_sse_stream(basic_server, basic_server_url):
    """Test establishing an SSE stream via GET request."""
    # First, we need to initialize a session
    mcp_url = f"{basic_server_url}/mcp"
    init_response = requests.post(
        mcp_url,
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json=INIT_REQUEST,
    )
    assert init_response.status_code == 200

    # Get the session ID
    session_id = init_response.headers.get(MCP_SESSION_ID_HEADER)
    assert session_id is not None

    # Now attempt to establish an SSE stream via GET
    get_response = requests.get(
        mcp_url,
        headers={
            "Accept": "text/event-stream",
            MCP_SESSION_ID_HEADER: session_id,
        },
        stream=True,
    )

    # Verify we got a successful response with the right content type
    assert get_response.status_code == 200
    assert get_response.headers.get("Content-Type") == "text/event-stream"

    # Test that a second GET request gets rejected (only one stream allowed)
    second_get = requests.get(
        mcp_url,
        headers={
            "Accept": "text/event-stream",
            MCP_SESSION_ID_HEADER: session_id,
        },
        stream=True,
    )

    # Should get CONFLICT (409) since there's already a stream
    # Note: This might fail if the first stream fully closed before this runs,
    # but generally it should work in the test environment where it runs quickly
    assert second_get.status_code == 409


def test_get_validation(basic_server, basic_server_url):
    """Test validation for GET requests."""
    # First, we need to initialize a session
    mcp_url = f"{basic_server_url}/mcp"
    init_response = requests.post(
        mcp_url,
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json=INIT_REQUEST,
    )
    assert init_response.status_code == 200

    # Get the session ID
    session_id = init_response.headers.get(MCP_SESSION_ID_HEADER)
    assert session_id is not None

    # Test without Accept header
    response = requests.get(
        mcp_url,
        headers={
            MCP_SESSION_ID_HEADER: session_id,
        },
        stream=True,
    )
    assert response.status_code == 406
    assert "Not Acceptable" in response.text

    # Test with wrong Accept header
    response = requests.get(
        mcp_url,
        headers={
            "Accept": "application/json",
            MCP_SESSION_ID_HEADER: session_id,
        },
    )
    assert response.status_code == 406
    assert "Not Acceptable" in response.text
