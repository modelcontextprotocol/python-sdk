import multiprocessing
import socket
import time
import json
from collections.abc import AsyncGenerator, Generator

import anyio
import httpx
import pytest
import uvicorn
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route

from mcp.server import Server
from mcp.server.streamable_http import StreamableHTTPServerTransport
from mcp.types import (
    Tool,
    TextContent,
    ErrorData,
)
from mcp.shared.exceptions import McpError

SERVER_NAME = "test_server_for_StreamableHTTP"


@pytest.fixture
def server_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server_url(server_port: int) -> str:
    return f"http://127.0.0.1:{server_port}"


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
                await anyio.sleep(0.5)
                return f"Slow response from {uri.host}"

            raise McpError(
                error=ErrorData(
                    code=404, message="Resource not found"
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
    """Create test Starlette app with Streamable HTTP transport"""
    transport = StreamableHTTPServerTransport()
    server = ServerTest()

    async def handle_http(request: Request) -> None:
        async with transport.connect_streamable_http(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0], streams[1], server.create_initialization_options(),
            )

    app = Starlette(
        routes=[
            Route("/mcp", endpoint=handle_http, methods=["GET", "POST", "DELETE"]),
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
    print(f"Starting server on {server_port}")
    server.run()


@pytest.fixture()
def server(server_port: int) -> Generator[None, None, None]:
    proc = multiprocessing.Process(
        target=run_server, kwargs={"server_port": server_port}, daemon=True
    )
    print("Starting process")
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
    # Signal the server to stop
    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():
        print("Server process failed to terminate")


@pytest.fixture()
async def http_client(server, server_url) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create test client"""
    async with httpx.AsyncClient(base_url=server_url) as client:
        yield client


# Tests for basic protocol compliance
@pytest.mark.anyio
async def test_raw_http_initialization(http_client: httpx.AsyncClient) -> None:
    """Test the HTTP initialization with a raw HTTP client."""
    # Test initialization with proper headers
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Origin": "http://localhost"
    }
    
    init_payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {},
        "id": "init-test"
    }
    
    response = await http_client.post("/mcp", json=init_payload, headers=headers)
    assert response.status_code == 200


@pytest.mark.anyio
async def test_missing_origin_header(http_client: httpx.AsyncClient) -> None:
    """Test that requests without Origin header are rejected."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        # Missing Origin header
    }
    
    init_payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {},
        "id": "init-test"
    }
    
    response = await http_client.post("/mcp", json=init_payload, headers=headers)
    assert response.status_code == 400  # Bad Request


@pytest.mark.anyio
async def test_invalid_content_type(http_client: httpx.AsyncClient) -> None:
    """Test that requests with invalid Content-Type are rejected."""
    headers = {
        "Content-Type": "text/plain",  # Invalid content type
        "Accept": "application/json, text/event-stream",
        "Origin": "http://localhost"
    }
    
    init_payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {},
        "id": "init-test"
    }
    
    response = await http_client.post("/mcp", json=init_payload, headers=headers)
    assert response.status_code == 415  # Unsupported Media Type


@pytest.mark.anyio
async def test_invalid_accept_header(http_client: httpx.AsyncClient) -> None:
    """Test that requests with invalid Accept header are rejected."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/plain",  # Missing required content types
        "Origin": "http://localhost"
    }
    
    init_payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {},
        "id": "init-test"
    }
    
    response = await http_client.post("/mcp", json=init_payload, headers=headers)
    assert response.status_code == 406  # Not Acceptable


@pytest.mark.anyio
async def test_sse_connection(http_client: httpx.AsyncClient) -> None:
    """Test that we can establish an SSE connection after initialization."""
    # First initialize
    init_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Origin": "http://localhost"
    }
    
    init_payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {},
        "id": "init-sse"
    }
    
    response = await http_client.post("/mcp", json=init_payload, headers=init_headers)
    assert response.status_code == 200
    
    # Get session ID if provided
    session_id = response.headers.get("mcp-session-id")
    
    # Now set up SSE connection
    sse_headers = {
        "Accept": "text/event-stream",
        "Origin": "http://localhost"
    }
    
    # Add session ID if we got one
    if session_id:
        sse_headers["mcp-session-id"] = session_id
    
    # Try to establish SSE connection (GET request)
    async with http_client.stream("GET", "/mcp", headers=sse_headers) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]


# Tests for stateless operation
@pytest.mark.anyio
async def test_stateless_operation(http_client: httpx.AsyncClient) -> None:
    """Test that the transport works in stateless mode without session IDs."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Origin": "http://localhost"
    }
    
    # Initialize first
    init_payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {},
        "id": "init-stateless"
    }
    
    init_response = await http_client.post("/mcp", json=init_payload, headers=headers)
    assert init_response.status_code == 200
    
    # In stateless mode, there should be no session ID header
    # In stateful mode, there should be a session ID header
    session_id = init_response.headers.get("mcp-session-id")
    # Send a standard MCP method request (list_tools is a standard MCP method)
    list_tools_payload = {
        "jsonrpc": "2.0",
        "method": "list_tools",
        "params": {},
        "id": "list-tools-stateless"
    }
    
    # Don't include session ID header even if we got one from init
    response = await http_client.post("/mcp", json=list_tools_payload, headers=headers)
    # In true stateless mode, this should always succeed without a session ID
    assert response.status_code in (200, 202)
    
    # If we got a session ID from init, also test with it
    # This confirms the server accepts requests both with and without session IDs in stateless mode
    if session_id:
        # Create headers with session ID
        session_headers = headers.copy()
        session_headers["mcp-session-id"] = session_id
        
        # Send the same request but with session ID
        response_with_session = await http_client.post("/mcp", json=list_tools_payload, headers=session_headers)
        assert response_with_session.status_code in (200, 202)


# Tests for session management
@pytest.mark.anyio
async def test_session_management(http_client: httpx.AsyncClient) -> None:
    """Test session management with proper session ID headers."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Origin": "http://localhost"
    }
    
    # Initialize to get a session
    init_payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {},
        "id": "init-session"
    }
    
    init_response = await http_client.post("/mcp", json=init_payload, headers=headers)
    assert init_response.status_code == 200
    
    # If we got a session ID, use it in subsequent requests
    session_id = init_response.headers.get("mcp-session-id")
    if session_id:
        # Add session ID to headers
        headers["mcp-session-id"] = session_id
        
        # Make a request with the session ID
        ping_payload = {
            "jsonrpc": "2.0",
            "method": "ping",
            "params": {},
            "id": "ping-with-session"
        }
        
        response = await http_client.post("/mcp", json=ping_payload, headers=headers)
        assert response.status_code in (200, 202)
        
        # Try an invalid session ID
        invalid_headers = headers.copy()
        invalid_headers["mcp-session-id"] = "invalid-session-id"
        
        invalid_response = await http_client.post("/mcp", json=ping_payload, headers=invalid_headers)
        # Should fail with 404 (Not Found) for invalid session
        assert invalid_response.status_code == 404


@pytest.mark.anyio
async def test_delete_session(http_client: httpx.AsyncClient) -> None:
    """Test session termination with DELETE method."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Origin": "http://localhost"
    }
    
    # Initialize to get a session
    init_payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {},
        "id": "init-delete-test"
    }
    
    response = await http_client.post("/mcp", json=init_payload, headers=headers)
    assert response.status_code == 200
    
    session_id = response.headers.get("mcp-session-id")
    if session_id:
        # If we got a session ID (stateful mode), test deleting it
        headers["mcp-session-id"] = session_id
        response = await http_client.delete("/mcp", headers=headers)
        assert response.status_code == 200


@pytest.mark.anyio
async def test_batch_requests(http_client: httpx.AsyncClient) -> None:
    """Test handling of batch requests."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Origin": "http://localhost"
    }
    
    # Initialize first
    init_payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {},
        "id": "init-batch"
    }
    
    init_response = await http_client.post("/mcp", json=init_payload, headers=headers)
    assert init_response.status_code == 200
    
    # Get session ID if provided
    session_id = init_response.headers.get("mcp-session-id")
    if session_id:
        headers["mcp-session-id"] = session_id
    
    # Send a batch of notifications (no IDs)
    batch_notifications = [
        {
            "jsonrpc": "2.0",
            "method": "notify1",
            "params": {"message": "Notification 1"}
        },
        {
            "jsonrpc": "2.0",
            "method": "notify2",
            "params": {"message": "Notification 2"}
        }
    ]
    
    notification_response = await http_client.post("/mcp", json=batch_notifications, headers=headers)
    assert notification_response.status_code == 202  # Accepted
    
    # Send a batch with requests (with IDs)
    batch_requests = [
        {
            "jsonrpc": "2.0",
            "method": "ping",
            "params": {},
            "id": "batch-req-1"
        },
        {
            "jsonrpc": "2.0",
            "method": "ping",
            "params": {},
            "id": "batch-req-2"
        }
    ]
    
    # For requests, the response might be immediate JSON or use SSE
    request_response = await http_client.post("/mcp", json=batch_requests, headers=headers)
    assert request_response.status_code in (200, 202)
    
    # If 200 and JSON, check for batch response structure
    if request_response.status_code == 200 and "application/json" in request_response.headers.get("content-type", ""):
        response_data = request_response.json()
        assert isinstance(response_data, list)
        assert len(response_data) == 2
        request_ids = [resp.get("id") for resp in response_data]
        assert "batch-req-1" in request_ids
        assert "batch-req-2" in request_ids


@pytest.mark.anyio
async def test_invalid_json(http_client: httpx.AsyncClient) -> None:
    """Test handling of invalid JSON input."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Origin": "http://localhost"
    }
    
    # Send invalid JSON
    response = await http_client.post(
        "/mcp", 
        content="{invalid json",  # Intentionally malformed
        headers=headers
    )
    
    assert response.status_code == 400  # Bad Request
    response_data = response.json()
    assert "error" in response_data
    assert "code" in response_data["error"]
    assert response_data["error"]["code"] == -32700  # Parse error


@pytest.mark.anyio
async def test_multiple_initialize_rejected(http_client: httpx.AsyncClient) -> None:
    """Test that multiple initialization requests are rejected."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Origin": "http://localhost"
    }
    
    # First initialization
    init1_payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {},
        "id": "init-1"
    }
    
    init1_response = await http_client.post("/mcp", json=init1_payload, headers=headers)
    assert init1_response.status_code == 200
    
    # Get session ID if provided
    session_id = init1_response.headers.get("mcp-session-id")
    if session_id:
        headers["mcp-session-id"] = session_id
    
    # Second initialization - should be rejected
    init2_payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {},
        "id": "init-2"
    }
    
    init2_response = await http_client.post("/mcp", json=init2_payload, headers=headers)
    assert init2_response.status_code == 400  # Bad Request
