"""
Tests for the StreamableHTTP server and client transport.

Contains tests for both server and client sides of the StreamableHTTP transport.
"""

import contextlib
import multiprocessing
import socket
import time
from collections.abc import Generator
from http import HTTPStatus
from uuid import uuid4

import anyio
import httpx
import pytest
import requests
import uvicorn
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server import Server
from mcp.server.streamable_http import (
    MCP_SESSION_ID_HEADER,
    SESSION_ID_PATTERN,
    EventCallback,
    EventId,
    EventMessage,
    EventStore,
    StreamableHTTPServerTransport,
    StreamId,
)
from mcp.shared.exceptions import McpError
from mcp.shared.message import (
    ClientMessageMetadata,
)
from mcp.shared.session import RequestResponder
from mcp.types import (
    InitializeResult,
    TextContent,
    TextResourceContents,
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


# Simple in-memory event store for testing
class SimpleEventStore(EventStore):
    """Simple in-memory event store for testing."""

    def __init__(self):
        self._events: list[tuple[StreamId, EventId, types.JSONRPCMessage]] = []
        self._event_id_counter = 0

    async def store_event(
        self, stream_id: StreamId, message: types.JSONRPCMessage
    ) -> EventId:
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
        # Find the index of the last event ID
        start_index = None
        for i, (_, event_id, _) in enumerate(self._events):
            if event_id == last_event_id:
                start_index = i + 1
                break

        if start_index is None:
            # If event ID not found, start from beginning
            start_index = 0

        stream_id = None
        # Replay events
        for _, event_id, message in self._events[start_index:]:
            await send_callback(EventMessage(message, event_id))
            # Capture the stream ID from the first replayed event
            if stream_id is None and len(self._events) > start_index:
                stream_id = self._events[start_index][0]

        return stream_id


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
            ]

        @self.call_tool()
        async def handle_call_tool(name: str, args: dict) -> list[TextContent]:
            ctx = self.request_context

            # When the tool is called, send a notification to test GET stream
            if name == "test_tool_with_standalone_notification":
                await ctx.session.send_resource_updated(
                    uri=AnyUrl("http://test_resource")
                )
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

            return [TextContent(type="text", text=f"Called {name}")]


def create_app(
    is_json_response_enabled=False, event_store: EventStore | None = None
) -> Starlette:
    """Create a Starlette application for testing that matches the example server.

    Args:
        is_json_response_enabled: If True, use JSON responses instead of SSE streams.
        event_store: Optional event store for testing resumability.
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
            try:
                yield
            finally:
                if task_group:
                    tg.cancel_scope.cancel()
                    task_group = None

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
                    event_store=event_store,
                )

                async def run_server(task_status=None):
                    async with http_transport.connect() as streams:
                        read_stream, write_stream = streams
                        if task_status:
                            task_status.started()
                        await server.run(
                            read_stream,
                            write_stream,
                            server.create_initialization_options(),
                        )

                if task_group is None:
                    response = Response(
                        "Internal Server Error: Task group is not initialized",
                        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                    await response(scope, receive, send)
                    return

                # Store the instance before starting the task to prevent races
                server_instances[http_transport.mcp_session_id] = http_transport
                await task_group.start(run_server)

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


def run_server(
    port: int, is_json_response_enabled=False, event_store: EventStore | None = None
) -> None:
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


# Client-specific fixtures
@pytest.fixture
async def http_client(basic_server, basic_server_url):
    """Create test client matching the SSE test pattern."""
    async with httpx.AsyncClient(base_url=basic_server_url) as client:
        yield client


@pytest.fixture
async def initialized_client_session(basic_server, basic_server_url):
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
async def test_streamablehttp_client_basic_connection(basic_server, basic_server_url):
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
async def test_streamablehttp_client_resource_read(initialized_client_session):
    """Test client resource read functionality."""
    response = await initialized_client_session.read_resource(
        uri=AnyUrl("foobar://test-resource")
    )
    assert len(response.contents) == 1
    assert response.contents[0].uri == AnyUrl("foobar://test-resource")
    assert response.contents[0].text == "Read test-resource"


@pytest.mark.anyio
async def test_streamablehttp_client_tool_invocation(initialized_client_session):
    """Test client tool invocation."""
    # First list tools
    tools = await initialized_client_session.list_tools()
    assert len(tools.tools) == 3
    assert tools.tools[0].name == "test_tool"

    # Call the tool
    result = await initialized_client_session.call_tool("test_tool", {})
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert result.content[0].text == "Called test_tool"


@pytest.mark.anyio
async def test_streamablehttp_client_error_handling(initialized_client_session):
    """Test error handling in client."""
    with pytest.raises(McpError) as exc_info:
        await initialized_client_session.read_resource(
            uri=AnyUrl("unknown://test-error")
        )
    assert exc_info.value.error.code == 0
    assert "Unknown resource: unknown://test-error" in exc_info.value.error.message


@pytest.mark.anyio
async def test_streamablehttp_client_session_persistence(
    basic_server, basic_server_url
):
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
            assert len(tools.tools) == 3

            # Read a resource
            resource = await session.read_resource(uri=AnyUrl("foobar://test-persist"))
            assert isinstance(resource.contents[0], TextResourceContents) is True
            content = resource.contents[0]
            assert isinstance(content, TextResourceContents)
            assert content.text == "Read test-persist"


@pytest.mark.anyio
async def test_streamablehttp_client_json_response(
    json_response_server, json_server_url
):
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
            assert len(tools.tools) == 3

            # Call a tool and verify JSON response handling
            result = await session.call_tool("test_tool", {})
            assert len(result.content) == 1
            assert result.content[0].type == "text"
            assert result.content[0].text == "Called test_tool"


@pytest.mark.anyio
async def test_streamablehttp_client_get_stream(basic_server, basic_server_url):
    """Test GET stream functionality for server-initiated messages."""
    import mcp.types as types
    from mcp.shared.session import RequestResponder

    notifications_received = []

    # Define message handler to capture notifications
    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult]
        | types.ServerNotification
        | Exception,
    ) -> None:
        if isinstance(message, types.ServerNotification):
            notifications_received.append(message)

    async with streamablehttp_client(f"{basic_server_url}/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(
            read_stream, write_stream, message_handler=message_handler
        ) as session:
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

            assert (
                resource_update_found
            ), "ResourceUpdatedNotification not received via GET stream"


@pytest.mark.anyio
async def test_streamablehttp_client_session_termination(
    basic_server, basic_server_url
):
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
            assert len(tools.tools) == 3

    headers = {}
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
async def test_streamablehttp_client_resumption(event_server):
    """Test client session to resume a long running tool."""
    _, server_url = event_server

    # Variables to track the state
    captured_session_id = None
    captured_resumption_token = None
    captured_notifications = []
    tool_started = False

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult]
        | types.ServerNotification
        | Exception,
    ) -> None:
        if isinstance(message, types.ServerNotification):
            captured_notifications.append(message)
            # Look for our special notification that indicates the tool is running
            if isinstance(message.root, types.LoggingMessageNotification):
                if message.root.params.data == "Tool started":
                    nonlocal tool_started
                    tool_started = True

    async def on_resumption_token_update(token: str) -> None:
        nonlocal captured_resumption_token
        captured_resumption_token = token

    # First, start the client session and begin the long-running tool
    async with streamablehttp_client(f"{server_url}/mcp", terminate_on_close=False) as (
        read_stream,
        write_stream,
        get_session_id,
    ):
        async with ClientSession(
            read_stream, write_stream, message_handler=message_handler
        ) as session:
            # Initialize the session
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            captured_session_id = get_session_id()
            assert captured_session_id is not None

            # Start a long-running tool in a task
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
                                    name="long_running_with_checkpoints", arguments={}
                                ),
                            )
                        ),
                        types.CallToolResult,
                        metadata=metadata,
                    )

                tg.start_soon(run_tool)

                # Wait for the tool to start and at least one notification
                # and then kill the task group
                while not tool_started or not captured_resumption_token:
                    await anyio.sleep(0.1)
                tg.cancel_scope.cancel()

    # Store pre notifications and clear the captured notifications
    # for the post-resumption check
    captured_notifications_pre = captured_notifications.copy()
    captured_notifications = []

    # Now resume the session with the same mcp-session-id
    headers = {}
    if captured_session_id:
        headers[MCP_SESSION_ID_HEADER] = captured_session_id

    async with streamablehttp_client(f"{server_url}/mcp", headers=headers) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(
            read_stream, write_stream, message_handler=message_handler
        ) as session:
            # Don't initialize - just use the existing session

            # Resume the tool with the resumption token
            assert captured_resumption_token is not None

            metadata = ClientMessageMetadata(
                resumption_token=captured_resumption_token,
            )
            result = await session.send_request(
                types.ClientRequest(
                    types.CallToolRequest(
                        method="tools/call",
                        params=types.CallToolRequestParams(
                            name="long_running_with_checkpoints", arguments={}
                        ),
                    )
                ),
                types.CallToolResult,
                metadata=metadata,
            )

            # We should get a complete result
            assert len(result.content) == 1
            assert result.content[0].type == "text"
            assert "Completed" in result.content[0].text

            # We should have received the remaining notifications
            assert len(captured_notifications) > 0

            # Should not have the first notification
            # Check that "Tool started" notification isn't repeated when resuming
            assert not any(
                isinstance(n.root, types.LoggingMessageNotification)
                and n.root.params.data == "Tool started"
                for n in captured_notifications
            )
            # there is no intersection between pre and post notifications
            assert not any(
                n in captured_notifications_pre for n in captured_notifications
            )
