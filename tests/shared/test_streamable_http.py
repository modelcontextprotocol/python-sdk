"""
Tests for the StreamableHTTP server and client transport.

Contains tests for both server and client sides of the StreamableHTTP transport.
"""

import json
import multiprocessing
import socket
import time
from collections.abc import Generator
from typing import Any

import anyio
import httpx
import pytest
import requests
import uvicorn
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server import Server
from mcp.server.streamable_http import (
    MCP_PROTOCOL_VERSION_HEADER,
    MCP_SESSION_ID_HEADER,
    SESSION_ID_PATTERN,
    EventCallback,
    EventId,
    EventMessage,
    EventStore,
    StreamableHTTPServerTransport,
    StreamId,
)
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.context import RequestContext
from mcp.shared.exceptions import McpError
from mcp.shared.message import ClientMessageMetadata
from mcp.shared.session import RequestResponder
from mcp.types import InitializeResult, TextContent, TextResourceContents, Tool

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


# Helper functions
def extract_protocol_version_from_sse(response: requests.Response) -> str:
    """Extract the negotiated protocol version from an SSE initialization response."""
    assert response.headers.get("Content-Type") == "text/event-stream"
    for line in response.text.splitlines():
        if line.startswith("data: "):
            init_data = json.loads(line[6:])
            return init_data["result"]["protocolVersion"]
    raise ValueError("Could not extract protocol version from SSE response")


# Simple in-memory event store for testing
class SimpleEventStore(EventStore):
    """Simple in-memory event store for testing."""

    def __init__(self):
        self._events: list[tuple[StreamId, EventId, types.JSONRPCMessage]] = []
        self._event_id_counter = 0

    async def store_event(self, stream_id: StreamId, message: types.JSONRPCMessage) -> EventId:
        """Store an event and return its ID."""
        self._event_id_counter += 1
        event_id = str(self._event_id_counter)
        self._events.append((stream_id, event_id, message))
        return event_id

    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: EventCallback,
    ) -> StreamId | None:
        """Replay events after the specified ID."""
        # Find the stream ID of the last event
        target_stream_id = None
        for stream_id, event_id, _ in self._events:
            if event_id == last_event_id:
                target_stream_id = stream_id
                break

        if target_stream_id is None:
            # If event ID not found, return None
            return None

        # Convert last_event_id to int for comparison
        last_event_id_int = int(last_event_id)

        # Replay only events from the same stream with ID > last_event_id
        for stream_id, event_id, message in self._events:
            if stream_id == target_stream_id and int(event_id) > last_event_id_int:
                await send_callback(EventMessage(message, event_id))

        return target_stream_id


# Test server implementation that follows MCP protocol
class ServerTest(Server):
    def __init__(self):
        super().__init__(SERVER_NAME)
        self._lock = None  # Will be initialized in async context

        @self.read_resource()
        async def handle_read_resource(uri: AnyUrl) -> str | bytes:
            if uri.scheme == "foobar":
                return f"Read {uri.host}"
            elif uri.scheme == "slow":
                # Simulate a slow resource
                await anyio.sleep(2.0)
                return f"Slow response from {uri.host}"

            raise ValueError(f"Unknown resource: {uri}")

        @self.list_tools()
        async def handle_list_tools() -> list[Tool]:
            return [
                Tool(
                    name="test_tool",
                    description="A test tool",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="test_tool_with_standalone_notification",
                    description="A test tool that sends a notification",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="long_running_with_checkpoints",
                    description="A long-running tool that sends periodic notifications",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="test_sampling_tool",
                    description="A tool that triggers server-side sampling",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="wait_for_lock_with_notification",
                    description="A tool that sends a notification and waits for lock",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="release_lock",
                    description="A tool that releases the lock",
                    inputSchema={"type": "object", "properties": {}},
                ),
            ]

        @self.call_tool()
        async def handle_call_tool(name: str, args: dict[str, Any]) -> list[TextContent]:
            ctx = self.request_context

            # When the tool is called, send a notification to test GET stream
            if name == "test_tool_with_standalone_notification":
                await ctx.session.send_resource_updated(uri=AnyUrl("http://test_resource"))
                return [TextContent(type="text", text=f"Called {name}")]

            elif name == "long_running_with_checkpoints":
                # Send notifications that are part of the response stream
                # This simulates a long-running tool that sends logs

                await ctx.session.send_log_message(
                    level="info",
                    data="Tool started",
                    logger="tool",
                    related_request_id=ctx.request_id,  # need for stream association
                )

                await anyio.sleep(0.1)

                await ctx.session.send_log_message(
                    level="info",
                    data="Tool is almost done",
                    logger="tool",
                    related_request_id=ctx.request_id,
                )

                return [TextContent(type="text", text="Completed!")]

            elif name == "test_sampling_tool":
                # Test sampling by requesting the client to sample a message
                sampling_result = await ctx.session.create_message(
                    messages=[
                        types.SamplingMessage(
                            role="user",
                            content=types.TextContent(type="text", text="Server needs client sampling"),
                        )
                    ],
                    max_tokens=100,
                    related_request_id=ctx.request_id,
                )

                # Return the sampling result in the tool response
                response = sampling_result.content.text if sampling_result.content.type == "text" else None
                return [
                    TextContent(
                        type="text",
                        text=f"Response from sampling: {response}",
                    )
                ]

            elif name == "wait_for_lock_with_notification":
                # Initialize lock if not already done
                if self._lock is None:
                    self._lock = anyio.Event()

                # First send a notification
                await ctx.session.send_log_message(
                    level="info",
                    data="First notification before lock",
                    logger="lock_tool",
                    related_request_id=ctx.request_id,
                )

                # Now wait for the lock to be released
                await self._lock.wait()

                # Send second notification after lock is released
                await ctx.session.send_log_message(
                    level="info",
                    data="Second notification after lock",
                    logger="lock_tool",
                    related_request_id=ctx.request_id,
                )

                return [TextContent(type="text", text="Completed")]

            elif name == "release_lock":
                assert self._lock is not None, "Lock must be initialized before releasing"

                # Release the lock
                self._lock.set()
                return [TextContent(type="text", text="Lock released")]

            return [TextContent(type="text", text=f"Called {name}")]


def create_app(is_json_response_enabled: bool = False, event_store: EventStore | None = None) -> Starlette:
    """Create a Starlette application for testing using the session manager.

    Args:
        is_json_response_enabled: If True, use JSON responses instead of SSE streams.
        event_store: Optional event store for testing resumability.
    """
    # Create server instance
    server = ServerTest()

    # Create the session manager
    security_settings = TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*"], allowed_origins=["http://127.0.0.1:*", "http://localhost:*"]
    )
    session_manager = StreamableHTTPSessionManager(
        app=server,
        event_store=event_store,
        json_response=is_json_response_enabled,
        security_settings=security_settings,
    )

    # Create an ASGI application that uses the session manager
    app = Starlette(
        debug=True,
        routes=[
            Mount("/mcp", app=session_manager.handle_request),
        ],
        lifespan=lambda app: session_manager.run(),
    )

    return app


def run_server(port: int, is_json_response_enabled: bool = False, event_store: EventStore | None = None) -> None:
    """Run the test server.

    Args:
        port: Port to listen on.
        is_json_response_enabled: If True, use JSON responses instead of SSE streams.
        event_store: Optional event store for testing resumability.
    """

    app = create_app(is_json_response_enabled, event_store)
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
        server.run()
    except Exception:
        import traceback

        traceback.print_exc()


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
    proc = multiprocessing.Process(target=run_server, kwargs={"port": basic_server_port}, daemon=True)
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


@pytest.fixture
def event_store() -> SimpleEventStore:
    """Create a test event store."""
    return SimpleEventStore()


@pytest.fixture
def event_server_port() -> int:
    """Find an available port for the event store server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def event_server(
    event_server_port: int, event_store: SimpleEventStore
) -> Generator[tuple[SimpleEventStore, str], None, None]:
    """Start a server with event store enabled."""
    proc = multiprocessing.Process(
        target=run_server,
        kwargs={"port": event_server_port, "event_store": event_store},
        daemon=True,
    )
    proc.start()

    # Wait for server to be running
    max_attempts = 20
    attempt = 0
    while attempt < max_attempts:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", event_server_port))
                break
        except ConnectionRefusedError:
            time.sleep(0.1)
            attempt += 1
    else:
        raise RuntimeError(f"Server failed to start after {max_attempts} attempts")

    yield event_store, f"http://127.0.0.1:{event_server_port}"

    # Clean up
    proc.kill()
    proc.join(timeout=2)


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


@pytest.fixture
def basic_server_url(basic_server_port: int) -> str:
    """Get the URL for the basic test server."""
    return f"http://127.0.0.1:{basic_server_port}"


@pytest.fixture
def json_server_url(json_server_port: int) -> str:
    """Get the URL for the JSON response test server."""
    return f"http://127.0.0.1:{json_server_port}"


# Basic request validation tests
def test_accept_header_validation(basic_server: None, basic_server_url: str):
    """Test that Accept header is properly validated."""
    # Test without Accept header
    response = requests.post(
        f"{basic_server_url}/mcp",
        headers={"Content-Type": "application/json"},
        json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
    )
    assert response.status_code == 406
    assert "Not Acceptable" in response.text


def test_content_type_validation(basic_server: None, basic_server_url: str):
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

    assert response.status_code == 400
    assert "Invalid Content-Type" in response.text


def test_json_validation(basic_server: None, basic_server_url: str):
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


def test_json_parsing(basic_server: None, basic_server_url: str):
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


def test_method_not_allowed(basic_server: None, basic_server_url: str):
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


def test_session_validation(basic_server: None, basic_server_url: str):
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


def test_session_termination(basic_server: None, basic_server_url: str):
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

    # Extract negotiated protocol version from SSE response
    negotiated_version = extract_protocol_version_from_sse(response)

    # Now terminate the session
    session_id = response.headers.get(MCP_SESSION_ID_HEADER)
    response = requests.delete(
        f"{basic_server_url}/mcp",
        headers={
            MCP_SESSION_ID_HEADER: session_id,
            MCP_PROTOCOL_VERSION_HEADER: negotiated_version,
        },
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


def test_response(basic_server: None, basic_server_url: str):
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

    # Extract negotiated protocol version from SSE response
    negotiated_version = extract_protocol_version_from_sse(response)

    # Now get the session ID
    session_id = response.headers.get(MCP_SESSION_ID_HEADER)

    # Try to use the session with proper headers
    tools_response = requests.post(
        mcp_url,
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            MCP_SESSION_ID_HEADER: session_id,  # Use the session ID we got earlier
            MCP_PROTOCOL_VERSION_HEADER: negotiated_version,
        },
        json={"jsonrpc": "2.0", "method": "tools/list", "id": "tools-1"},
        stream=True,
    )
    assert tools_response.status_code == 200
    assert tools_response.headers.get("Content-Type") == "text/event-stream"


def test_json_response(json_response_server: None, json_server_url: str):
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


def test_get_sse_stream(basic_server: None, basic_server_url: str):
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

    # Extract negotiated protocol version from SSE response
    init_data = None
    assert init_response.headers.get("Content-Type") == "text/event-stream"
    for line in init_response.text.splitlines():
        if line.startswith("data: "):
            init_data = json.loads(line[6:])
            break
    assert init_data is not None
    negotiated_version = init_data["result"]["protocolVersion"]

    # Now attempt to establish an SSE stream via GET
    get_response = requests.get(
        mcp_url,
        headers={
            "Accept": "text/event-stream",
            MCP_SESSION_ID_HEADER: session_id,
            MCP_PROTOCOL_VERSION_HEADER: negotiated_version,
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
            MCP_PROTOCOL_VERSION_HEADER: negotiated_version,
        },
        stream=True,
    )

    # Should get CONFLICT (409) since there's already a stream
    # Note: This might fail if the first stream fully closed before this runs,
    # but generally it should work in the test environment where it runs quickly
    assert second_get.status_code == 409


def test_get_validation(basic_server: None, basic_server_url: str):
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

    # Extract negotiated protocol version from SSE response
    init_data = None
    assert init_response.headers.get("Content-Type") == "text/event-stream"
    for line in init_response.text.splitlines():
        if line.startswith("data: "):
            init_data = json.loads(line[6:])
            break
    assert init_data is not None
    negotiated_version = init_data["result"]["protocolVersion"]

    # Test without Accept header
    response = requests.get(
        mcp_url,
        headers={
            MCP_SESSION_ID_HEADER: session_id,
            MCP_PROTOCOL_VERSION_HEADER: negotiated_version,
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
            MCP_PROTOCOL_VERSION_HEADER: negotiated_version,
        },
    )
    assert response.status_code == 406
    assert "Not Acceptable" in response.text


# Client-specific fixtures
@pytest.fixture
async def http_client(basic_server: None, basic_server_url: str):
    """Create test client matching the SSE test pattern."""
    async with httpx.AsyncClient(base_url=basic_server_url) as client:
        yield client


@pytest.fixture
async def initialized_client_session(basic_server: None, basic_server_url: str):
    """Create initialized StreamableHTTP client session."""
    async with streamablehttp_client(f"{basic_server_url}/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
        ) as session:
            await session.initialize()
            yield session


@pytest.mark.anyio
async def test_streamablehttp_client_basic_connection(basic_server: None, basic_server_url: str):
    """Test basic client connection with initialization."""
    async with streamablehttp_client(f"{basic_server_url}/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
        ) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == SERVER_NAME


@pytest.mark.anyio
async def test_streamablehttp_client_resource_read(initialized_client_session: ClientSession):
    """Test client resource read functionality."""
    response = await initialized_client_session.read_resource(uri=AnyUrl("foobar://test-resource"))
    assert len(response.contents) == 1
    assert response.contents[0].uri == AnyUrl("foobar://test-resource")
    assert isinstance(response.contents[0], TextResourceContents)
    assert response.contents[0].text == "Read test-resource"


@pytest.mark.anyio
async def test_streamablehttp_client_tool_invocation(initialized_client_session: ClientSession):
    """Test client tool invocation."""
    # First list tools
    tools = await initialized_client_session.list_tools()
    assert len(tools.tools) == 6
    assert tools.tools[0].name == "test_tool"

    # Call the tool
    result = await initialized_client_session.call_tool("test_tool", {})
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert result.content[0].text == "Called test_tool"


@pytest.mark.anyio
async def test_streamablehttp_client_error_handling(initialized_client_session: ClientSession):
    """Test error handling in client."""
    with pytest.raises(McpError) as exc_info:
        await initialized_client_session.read_resource(uri=AnyUrl("unknown://test-error"))
    assert exc_info.value.error.code == 0
    assert "Unknown resource: unknown://test-error" in exc_info.value.error.message


@pytest.mark.anyio
async def test_streamablehttp_client_session_persistence(basic_server: None, basic_server_url: str):
    """Test that session ID persists across requests."""
    async with streamablehttp_client(f"{basic_server_url}/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
        ) as session:
            # Initialize the session
            result = await session.initialize()
            assert isinstance(result, InitializeResult)

            # Make multiple requests to verify session persistence
            tools = await session.list_tools()
            assert len(tools.tools) == 6

            # Read a resource
            resource = await session.read_resource(uri=AnyUrl("foobar://test-persist"))
            assert isinstance(resource.contents[0], TextResourceContents) is True
            content = resource.contents[0]
            assert isinstance(content, TextResourceContents)
            assert content.text == "Read test-persist"


@pytest.mark.anyio
async def test_streamablehttp_client_json_response(json_response_server: None, json_server_url: str):
    """Test client with JSON response mode."""
    async with streamablehttp_client(f"{json_server_url}/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
        ) as session:
            # Initialize the session
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == SERVER_NAME

            # Check tool listing
            tools = await session.list_tools()
            assert len(tools.tools) == 6

            # Call a tool and verify JSON response handling
            result = await session.call_tool("test_tool", {})
            assert len(result.content) == 1
            assert result.content[0].type == "text"
            assert result.content[0].text == "Called test_tool"


@pytest.mark.anyio
async def test_streamablehttp_client_get_stream(basic_server: None, basic_server_url: str):
    """Test GET stream functionality for server-initiated messages."""
    import mcp.types as types
    from mcp.shared.session import RequestResponder

    notifications_received: list[types.ServerNotification] = []

    # Define message handler to capture notifications
    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, types.ServerNotification):
            notifications_received.append(message)

    async with streamablehttp_client(f"{basic_server_url}/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream, message_handler=message_handler) as session:
            # Initialize the session - this triggers the GET stream setup
            result = await session.initialize()
            assert isinstance(result, InitializeResult)

            # Call the special tool that sends a notification
            await session.call_tool("test_tool_with_standalone_notification", {})

            # Verify we received the notification
            assert len(notifications_received) > 0

            # Verify the notification is a ResourceUpdatedNotification
            resource_update_found = False
            for notif in notifications_received:
                if isinstance(notif.root, types.ResourceUpdatedNotification):
                    assert str(notif.root.params.uri) == "http://test_resource/"
                    resource_update_found = True

            assert resource_update_found, "ResourceUpdatedNotification not received via GET stream"


@pytest.mark.anyio
async def test_streamablehttp_client_session_termination(basic_server: None, basic_server_url: str):
    """Test client session termination functionality."""

    captured_session_id = None

    # Create the streamablehttp_client with a custom httpx client to capture headers
    async with streamablehttp_client(f"{basic_server_url}/mcp") as (
        read_stream,
        write_stream,
        get_session_id,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            # Initialize the session
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            captured_session_id = get_session_id()
            assert captured_session_id is not None

            # Make a request to confirm session is working
            tools = await session.list_tools()
            assert len(tools.tools) == 6

    headers: dict[str, str] = {}
    if captured_session_id:
        headers[MCP_SESSION_ID_HEADER] = captured_session_id

    async with streamablehttp_client(f"{basic_server_url}/mcp", headers=headers) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            # Attempt to make a request after termination
            with pytest.raises(
                McpError,
                match="Session terminated",
            ):
                await session.list_tools()


@pytest.mark.anyio
async def test_streamablehttp_client_session_termination_204(
    basic_server: None, basic_server_url: str, monkeypatch: pytest.MonkeyPatch
):
    """Test client session termination functionality with a 204 response.

    This test patches the httpx client to return a 204 response for DELETEs.
    """

    # Save the original delete method to restore later
    original_delete = httpx.AsyncClient.delete

    # Mock the client's delete method to return a 204
    async def mock_delete(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> httpx.Response:
        # Call the original method to get the real response
        response = await original_delete(self, *args, **kwargs)

        # Create a new response with 204 status code but same headers
        mocked_response = httpx.Response(
            204,
            headers=response.headers,
            content=response.content,
            request=response.request,
        )
        return mocked_response

    # Apply the patch to the httpx client
    monkeypatch.setattr(httpx.AsyncClient, "delete", mock_delete)

    captured_session_id = None

    # Create the streamablehttp_client with a custom httpx client to capture headers
    async with streamablehttp_client(f"{basic_server_url}/mcp") as (
        read_stream,
        write_stream,
        get_session_id,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            # Initialize the session
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            captured_session_id = get_session_id()
            assert captured_session_id is not None

            # Make a request to confirm session is working
            tools = await session.list_tools()
            assert len(tools.tools) == 6

    headers: dict[str, str] = {}
    if captured_session_id:
        headers[MCP_SESSION_ID_HEADER] = captured_session_id

    async with streamablehttp_client(f"{basic_server_url}/mcp", headers=headers) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            # Attempt to make a request after termination
            with pytest.raises(
                McpError,
                match="Session terminated",
            ):
                await session.list_tools()


@pytest.mark.anyio
async def test_streamablehttp_client_resumption(event_server: tuple[SimpleEventStore, str]):
    """Test client session resumption using sync primitives for reliable coordination."""
    _, server_url = event_server

    # Variables to track the state
    captured_session_id = None
    captured_resumption_token = None
    captured_notifications: list[types.ServerNotification] = []
    captured_protocol_version = None
    first_notification_received = False

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, types.ServerNotification):
            captured_notifications.append(message)
            # Look for our first notification
            if isinstance(message.root, types.LoggingMessageNotification):
                if message.root.params.data == "First notification before lock":
                    nonlocal first_notification_received
                    first_notification_received = True

    async def on_resumption_token_update(token: str) -> None:
        nonlocal captured_resumption_token
        captured_resumption_token = token

    # First, start the client session and begin the tool that waits on lock
    async with streamablehttp_client(f"{server_url}/mcp", terminate_on_close=False) as (
        read_stream,
        write_stream,
        get_session_id,
    ):
        async with ClientSession(read_stream, write_stream, message_handler=message_handler) as session:
            # Initialize the session
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            captured_session_id = get_session_id()
            assert captured_session_id is not None
            # Capture the negotiated protocol version
            captured_protocol_version = result.protocolVersion

            # Start the tool that will wait on lock in a task
            async with anyio.create_task_group() as tg:

                async def run_tool():
                    metadata = ClientMessageMetadata(
                        on_resumption_token_update=on_resumption_token_update,
                    )
                    await session.send_request(
                        types.ClientRequest(
                            types.CallToolRequest(
                                method="tools/call",
                                params=types.CallToolRequestParams(
                                    name="wait_for_lock_with_notification", arguments={}
                                ),
                            )
                        ),
                        types.CallToolResult,
                        metadata=metadata,
                    )

                tg.start_soon(run_tool)

                # Wait for the first notification and resumption token
                while not first_notification_received or not captured_resumption_token:
                    await anyio.sleep(0.1)

                # Kill the client session while tool is waiting on lock
                tg.cancel_scope.cancel()

    # Verify we received exactly one notification
    assert len(captured_notifications) == 1
    assert isinstance(captured_notifications[0].root, types.LoggingMessageNotification)
    assert captured_notifications[0].root.params.data == "First notification before lock"

    # Clear notifications for the second phase
    captured_notifications = []

    # Now resume the session with the same mcp-session-id and protocol version
    headers: dict[str, Any] = {}
    if captured_session_id:
        headers[MCP_SESSION_ID_HEADER] = captured_session_id
    if captured_protocol_version:
        headers[MCP_PROTOCOL_VERSION_HEADER] = captured_protocol_version
    async with streamablehttp_client(f"{server_url}/mcp", headers=headers) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream, message_handler=message_handler) as session:
            result = await session.send_request(
                types.ClientRequest(
                    types.CallToolRequest(
                        method="tools/call",
                        params=types.CallToolRequestParams(name="release_lock", arguments={}),
                    )
                ),
                types.CallToolResult,
            )
            metadata = ClientMessageMetadata(
                resumption_token=captured_resumption_token,
            )

            result = await session.send_request(
                types.ClientRequest(
                    types.CallToolRequest(
                        method="tools/call",
                        params=types.CallToolRequestParams(name="wait_for_lock_with_notification", arguments={}),
                    )
                ),
                types.CallToolResult,
                metadata=metadata,
            )
            assert len(result.content) == 1
            assert result.content[0].type == "text"
            assert result.content[0].text == "Completed"

            # We should have received the remaining notifications
            assert len(captured_notifications) == 1

            assert isinstance(captured_notifications[0].root, types.LoggingMessageNotification)
            assert captured_notifications[0].root.params.data == "Second notification after lock"


@pytest.mark.anyio
async def test_streamablehttp_server_sampling(basic_server: None, basic_server_url: str):
    """Test server-initiated sampling request through streamable HTTP transport."""
    # Variable to track if sampling callback was invoked
    sampling_callback_invoked = False
    captured_message_params = None

    # Define sampling callback that returns a mock response
    async def sampling_callback(
        context: RequestContext[ClientSession, Any],
        params: types.CreateMessageRequestParams,
    ) -> types.CreateMessageResult:
        nonlocal sampling_callback_invoked, captured_message_params
        sampling_callback_invoked = True
        captured_message_params = params
        message_received = params.messages[0].content.text if params.messages[0].content.type == "text" else None

        return types.CreateMessageResult(
            role="assistant",
            content=types.TextContent(
                type="text",
                text=f"Received message from server: {message_received}",
            ),
            model="test-model",
            stopReason="endTurn",
        )

    # Create client with sampling callback
    async with streamablehttp_client(f"{basic_server_url}/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
            sampling_callback=sampling_callback,
        ) as session:
            # Initialize the session
            result = await session.initialize()
            assert isinstance(result, InitializeResult)

            # Call the tool that triggers server-side sampling
            tool_result = await session.call_tool("test_sampling_tool", {})

            # Verify the tool result contains the expected content
            assert len(tool_result.content) == 1
            assert tool_result.content[0].type == "text"
            assert "Response from sampling: Received message from server" in tool_result.content[0].text

            # Verify sampling callback was invoked
            assert sampling_callback_invoked
            assert captured_message_params is not None
            assert len(captured_message_params.messages) == 1
            assert captured_message_params.messages[0].content.text == "Server needs client sampling"


# Context-aware server implementation for testing request context propagation
class ContextAwareServerTest(Server):
    def __init__(self):
        super().__init__("ContextAwareServer")

        @self.list_tools()
        async def handle_list_tools() -> list[Tool]:
            return [
                Tool(
                    name="echo_headers",
                    description="Echo request headers from context",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="echo_context",
                    description="Echo request context with custom data",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "request_id": {"type": "string"},
                        },
                        "required": ["request_id"],
                    },
                ),
            ]

        @self.call_tool()
        async def handle_call_tool(name: str, args: dict[str, Any]) -> list[TextContent]:
            ctx = self.request_context

            if name == "echo_headers":
                # Access the request object from context
                headers_info = {}
                if ctx.request and isinstance(ctx.request, Request):
                    headers_info = dict(ctx.request.headers)
                return [TextContent(type="text", text=json.dumps(headers_info))]

            elif name == "echo_context":
                # Return full context information
                context_data: dict[str, Any] = {
                    "request_id": args.get("request_id"),
                    "headers": {},
                    "method": None,
                    "path": None,
                }
                if ctx.request and isinstance(ctx.request, Request):
                    request = ctx.request
                    context_data["headers"] = dict(request.headers)
                    context_data["method"] = request.method
                    context_data["path"] = request.url.path
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(context_data),
                    )
                ]

            return [TextContent(type="text", text=f"Unknown tool: {name}")]


# Server runner for context-aware testing
def run_context_aware_server(port: int):
    """Run the context-aware test server."""
    server = ContextAwareServerTest()

    session_manager = StreamableHTTPSessionManager(
        app=server,
        event_store=None,
        json_response=False,
    )

    app = Starlette(
        debug=True,
        routes=[
            Mount("/mcp", app=session_manager.handle_request),
        ],
        lifespan=lambda app: session_manager.run(),
    )

    server_instance = uvicorn.Server(
        config=uvicorn.Config(
            app=app,
            host="127.0.0.1",
            port=port,
            log_level="error",
        )
    )
    server_instance.run()


@pytest.fixture
def context_aware_server(basic_server_port: int) -> Generator[None, None, None]:
    """Start the context-aware server in a separate process."""
    proc = multiprocessing.Process(target=run_context_aware_server, args=(basic_server_port,), daemon=True)
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
        raise RuntimeError(f"Context-aware server failed to start after {max_attempts} attempts")

    yield

    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():
        print("Context-aware server process failed to terminate")


@pytest.mark.anyio
async def test_streamablehttp_request_context_propagation(context_aware_server: None, basic_server_url: str) -> None:
    """Test that request context is properly propagated through StreamableHTTP."""
    custom_headers = {
        "Authorization": "Bearer test-token",
        "X-Custom-Header": "test-value",
        "X-Trace-Id": "trace-123",
    }

    async with streamablehttp_client(f"{basic_server_url}/mcp", headers=custom_headers) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == "ContextAwareServer"

            # Call the tool that echoes headers back
            tool_result = await session.call_tool("echo_headers", {})

            # Parse the JSON response
            assert len(tool_result.content) == 1
            assert isinstance(tool_result.content[0], TextContent)
            headers_data = json.loads(tool_result.content[0].text)

            # Verify headers were propagated
            assert headers_data.get("authorization") == "Bearer test-token"
            assert headers_data.get("x-custom-header") == "test-value"
            assert headers_data.get("x-trace-id") == "trace-123"


@pytest.mark.anyio
async def test_streamablehttp_request_context_isolation(context_aware_server: None, basic_server_url: str) -> None:
    """Test that request contexts are isolated between StreamableHTTP clients."""
    contexts: list[dict[str, Any]] = []

    # Create multiple clients with different headers
    for i in range(3):
        headers = {
            "X-Request-Id": f"request-{i}",
            "X-Custom-Value": f"value-{i}",
            "Authorization": f"Bearer token-{i}",
        }

        async with streamablehttp_client(f"{basic_server_url}/mcp", headers=headers) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Call the tool that echoes context
                tool_result = await session.call_tool("echo_context", {"request_id": f"request-{i}"})

                assert len(tool_result.content) == 1
                assert isinstance(tool_result.content[0], TextContent)
                context_data = json.loads(tool_result.content[0].text)
                contexts.append(context_data)

    # Verify each request had its own context
    assert len(contexts) == 3
    for i, ctx in enumerate(contexts):
        assert ctx["request_id"] == f"request-{i}"
        assert ctx["headers"].get("x-request-id") == f"request-{i}"
        assert ctx["headers"].get("x-custom-value") == f"value-{i}"
        assert ctx["headers"].get("authorization") == f"Bearer token-{i}"


@pytest.mark.anyio
async def test_client_includes_protocol_version_header_after_init(context_aware_server: None, basic_server_url: str):
    """Test that client includes mcp-protocol-version header after initialization."""
    async with streamablehttp_client(f"{basic_server_url}/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            # Initialize and get the negotiated version
            init_result = await session.initialize()
            negotiated_version = init_result.protocolVersion

            # Call a tool that echoes headers to verify the header is present
            tool_result = await session.call_tool("echo_headers", {})

            assert len(tool_result.content) == 1
            assert isinstance(tool_result.content[0], TextContent)
            headers_data = json.loads(tool_result.content[0].text)

            # Verify protocol version header is present
            assert "mcp-protocol-version" in headers_data
            assert headers_data[MCP_PROTOCOL_VERSION_HEADER] == negotiated_version


def test_server_validates_protocol_version_header(basic_server: None, basic_server_url: str):
    """Test that server returns 400 Bad Request version if header unsupported or invalid."""
    # First initialize a session to get a valid session ID
    init_response = requests.post(
        f"{basic_server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json=INIT_REQUEST,
    )
    assert init_response.status_code == 200
    session_id = init_response.headers.get(MCP_SESSION_ID_HEADER)

    # Test request with invalid protocol version (should fail)
    response = requests.post(
        f"{basic_server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            MCP_SESSION_ID_HEADER: session_id,
            MCP_PROTOCOL_VERSION_HEADER: "invalid-version",
        },
        json={"jsonrpc": "2.0", "method": "tools/list", "id": "test-2"},
    )
    assert response.status_code == 400
    assert MCP_PROTOCOL_VERSION_HEADER in response.text or "protocol version" in response.text.lower()

    # Test request with unsupported protocol version (should fail)
    response = requests.post(
        f"{basic_server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            MCP_SESSION_ID_HEADER: session_id,
            MCP_PROTOCOL_VERSION_HEADER: "1999-01-01",  # Very old unsupported version
        },
        json={"jsonrpc": "2.0", "method": "tools/list", "id": "test-3"},
    )
    assert response.status_code == 400
    assert MCP_PROTOCOL_VERSION_HEADER in response.text or "protocol version" in response.text.lower()

    # Test request with valid protocol version (should succeed)
    negotiated_version = extract_protocol_version_from_sse(init_response)

    response = requests.post(
        f"{basic_server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            MCP_SESSION_ID_HEADER: session_id,
            MCP_PROTOCOL_VERSION_HEADER: negotiated_version,
        },
        json={"jsonrpc": "2.0", "method": "tools/list", "id": "test-4"},
    )
    assert response.status_code == 200


def test_server_backwards_compatibility_no_protocol_version(basic_server: None, basic_server_url: str):
    """Test server accepts requests without protocol version header."""
    # First initialize a session to get a valid session ID
    init_response = requests.post(
        f"{basic_server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json=INIT_REQUEST,
    )
    assert init_response.status_code == 200
    session_id = init_response.headers.get(MCP_SESSION_ID_HEADER)

    # Test request without mcp-protocol-version header (backwards compatibility)
    response = requests.post(
        f"{basic_server_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            MCP_SESSION_ID_HEADER: session_id,
        },
        json={"jsonrpc": "2.0", "method": "tools/list", "id": "test-backwards-compat"},
        stream=True,
    )
    assert response.status_code == 200  # Should succeed for backwards compatibility
    assert response.headers.get("Content-Type") == "text/event-stream"


@pytest.mark.anyio
async def test_client_crash_handled(basic_server: None, basic_server_url: str):
    """Test that cases where the client crashes are handled gracefully."""

    # Simulate bad client that crashes after init
    async def bad_client():
        """Client that triggers ClosedResourceError"""
        async with streamablehttp_client(f"{basic_server_url}/mcp") as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                raise Exception("client crash")

    # Run bad client a few times to trigger the crash
    for _ in range(3):
        try:
            await bad_client()
        except Exception:
            pass
        await anyio.sleep(0.1)

    # Try a good client, it should still be able to connect and list tools
    async with streamablehttp_client(f"{basic_server_url}/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            tools = await session.list_tools()
            assert tools.tools
