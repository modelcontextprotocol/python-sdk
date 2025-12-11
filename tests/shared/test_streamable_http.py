"""
Tests for the StreamableHTTP server and client transport.

Contains tests for both server and client sides of the StreamableHTTP transport.
"""

import json
import multiprocessing
import socket
import time
from collections.abc import Generator
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

import anyio
import httpx
import pytest
import requests
import uvicorn
from httpx_sse import ServerSentEvent
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import (
    StreamableHTTPTransport,
    streamable_http_client,
    streamablehttp_client,  # pyright: ignore[reportDeprecated]
)
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
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.context import RequestContext
from mcp.shared.exceptions import McpError
from mcp.shared.message import ClientMessageMetadata, ServerMessageMetadata, SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import (
    InitializeResult,
    JSONRPCMessage,
    JSONRPCRequest,
    TextContent,
    TextResourceContents,
    Tool,
)
from tests.test_helpers import wait_for_server

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
def extract_protocol_version_from_sse(response: requests.Response) -> str:  # pragma: no cover
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
        self._events: list[tuple[StreamId, EventId, types.JSONRPCMessage | None]] = []
        self._event_id_counter = 0

    async def store_event(  # pragma: no cover
        self, stream_id: StreamId, message: types.JSONRPCMessage | None
    ) -> EventId:
        """Store an event and return its ID."""
        self._event_id_counter += 1
        event_id = str(self._event_id_counter)
        self._events.append((stream_id, event_id, message))
        return event_id

    async def replay_events_after(  # pragma: no cover
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
                # Skip priming events (None message)
                if message is not None:
                    await send_callback(EventMessage(message, event_id))

        return target_stream_id


# Test server implementation that follows MCP protocol
class ServerTest(Server):  # pragma: no cover
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
                Tool(
                    name="tool_with_stream_close",
                    description="A tool that closes SSE stream mid-operation",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="tool_with_multiple_notifications_and_close",
                    description="Tool that sends notification1, closes stream, sends notification2, notification3",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="tool_with_multiple_stream_closes",
                    description="Tool that closes SSE stream multiple times during execution",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "checkpoints": {"type": "integer", "default": 3},
                            "sleep_time": {"type": "number", "default": 0.2},
                        },
                    },
                ),
                Tool(
                    name="tool_with_standalone_stream_close",
                    description="Tool that closes standalone GET stream mid-operation",
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
                # Since we're not passing tools param, result.content is single content
                if sampling_result.content.type == "text":
                    response = sampling_result.content.text
                else:
                    response = str(sampling_result.content)
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

            elif name == "tool_with_stream_close":
                # Send notification before closing
                await ctx.session.send_log_message(
                    level="info",
                    data="Before close",
                    logger="stream_close_tool",
                    related_request_id=ctx.request_id,
                )
                # Close SSE stream (triggers client reconnect)
                assert ctx.close_sse_stream is not None
                await ctx.close_sse_stream()
                # Continue processing (events stored in event_store)
                await anyio.sleep(0.1)
                await ctx.session.send_log_message(
                    level="info",
                    data="After close",
                    logger="stream_close_tool",
                    related_request_id=ctx.request_id,
                )
                return [TextContent(type="text", text="Done")]

            elif name == "tool_with_multiple_notifications_and_close":
                # Send notification1
                await ctx.session.send_log_message(
                    level="info",
                    data="notification1",
                    logger="multi_notif_tool",
                    related_request_id=ctx.request_id,
                )
                # Close SSE stream
                assert ctx.close_sse_stream is not None
                await ctx.close_sse_stream()
                # Send notification2, notification3 (stored in event_store)
                await anyio.sleep(0.1)
                await ctx.session.send_log_message(
                    level="info",
                    data="notification2",
                    logger="multi_notif_tool",
                    related_request_id=ctx.request_id,
                )
                await ctx.session.send_log_message(
                    level="info",
                    data="notification3",
                    logger="multi_notif_tool",
                    related_request_id=ctx.request_id,
                )
                return [TextContent(type="text", text="All notifications sent")]

            elif name == "tool_with_multiple_stream_closes":
                num_checkpoints = args.get("checkpoints", 3)
                sleep_time = args.get("sleep_time", 0.2)

                for i in range(num_checkpoints):
                    await ctx.session.send_log_message(
                        level="info",
                        data=f"checkpoint_{i}",
                        logger="multi_close_tool",
                        related_request_id=ctx.request_id,
                    )

                    if ctx.close_sse_stream:
                        await ctx.close_sse_stream()

                    await anyio.sleep(sleep_time)

                return [TextContent(type="text", text=f"Completed {num_checkpoints} checkpoints")]

            elif name == "tool_with_standalone_stream_close":
                # Test for GET stream reconnection
                # 1. Send unsolicited notification via GET stream (no related_request_id)
                await ctx.session.send_resource_updated(uri=AnyUrl("http://notification_1"))

                # Small delay to ensure notification is flushed before closing
                await anyio.sleep(0.1)

                # 2. Close the standalone GET stream
                if ctx.close_standalone_sse_stream:
                    await ctx.close_standalone_sse_stream()

                # 3. Wait for client to reconnect (uses retry_interval from server, default 1000ms)
                await anyio.sleep(1.5)

                # 4. Send another notification on the new GET stream connection
                await ctx.session.send_resource_updated(uri=AnyUrl("http://notification_2"))

                return [TextContent(type="text", text="Standalone stream close test done")]

            return [TextContent(type="text", text=f"Called {name}")]


def create_app(
    is_json_response_enabled: bool = False,
    event_store: EventStore | None = None,
    retry_interval: int | None = None,
) -> Starlette:  # pragma: no cover
    """Create a Starlette application for testing using the session manager.

    Args:
        is_json_response_enabled: If True, use JSON responses instead of SSE streams.
        event_store: Optional event store for testing resumability.
        retry_interval: Retry interval in milliseconds for SSE polling.
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
        retry_interval=retry_interval,
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


def run_server(
    port: int,
    is_json_response_enabled: bool = False,
    event_store: EventStore | None = None,
    retry_interval: int | None = None,
) -> None:  # pragma: no cover
    """Run the test server.

    Args:
        port: Port to listen on.
        is_json_response_enabled: If True, use JSON responses instead of SSE streams.
        event_store: Optional event store for testing resumability.
        retry_interval: Retry interval in milliseconds for SSE polling.
    """

    app = create_app(is_json_response_enabled, event_store, retry_interval)
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
    wait_for_server(basic_server_port)

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
    """Start a server with event store and retry_interval enabled."""
    proc = multiprocessing.Process(
        target=run_server,
        kwargs={"port": event_server_port, "event_store": event_store, "retry_interval": 500},
        daemon=True,
    )
    proc.start()

    # Wait for server to be running
    wait_for_server(event_server_port)

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
    wait_for_server(json_server_port)

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


def test_json_response_accept_json_only(json_response_server: None, json_server_url: str):
    """Test that json_response servers only require application/json in Accept header."""
    mcp_url = f"{json_server_url}/mcp"
    response = requests.post(
        mcp_url,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json=INIT_REQUEST,
    )
    assert response.status_code == 200
    assert response.headers.get("Content-Type") == "application/json"


def test_json_response_missing_accept_header(json_response_server: None, json_server_url: str):
    """Test that json_response servers reject requests without Accept header."""
    mcp_url = f"{json_server_url}/mcp"
    response = requests.post(
        mcp_url,
        headers={
            "Content-Type": "application/json",
        },
        json=INIT_REQUEST,
    )
    assert response.status_code == 406
    assert "Not Acceptable" in response.text


def test_json_response_incorrect_accept_header(json_response_server: None, json_server_url: str):
    """Test that json_response servers reject requests with incorrect Accept header."""
    mcp_url = f"{json_server_url}/mcp"
    # Test with only text/event-stream (wrong for JSON server)
    response = requests.post(
        mcp_url,
        headers={
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        },
        json=INIT_REQUEST,
    )
    assert response.status_code == 406
    assert "Not Acceptable" in response.text


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
    for line in init_response.text.splitlines():  # pragma: no branch
        if line.startswith("data: "):  # pragma: no cover
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
    for line in init_response.text.splitlines():  # pragma: no branch
        if line.startswith("data: "):  # pragma: no cover
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
async def http_client(basic_server: None, basic_server_url: str):  # pragma: no cover
    """Create test client matching the SSE test pattern."""
    async with httpx.AsyncClient(base_url=basic_server_url) as client:
        yield client


@pytest.fixture
async def initialized_client_session(basic_server: None, basic_server_url: str):
    """Create initialized StreamableHTTP client session."""
    async with streamable_http_client(f"{basic_server_url}/mcp") as (
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
async def test_streamable_http_client_basic_connection(basic_server: None, basic_server_url: str):
    """Test basic client connection with initialization."""
    async with streamable_http_client(f"{basic_server_url}/mcp") as (
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
async def test_streamable_http_client_resource_read(initialized_client_session: ClientSession):
    """Test client resource read functionality."""
    response = await initialized_client_session.read_resource(uri=AnyUrl("foobar://test-resource"))
    assert len(response.contents) == 1
    assert response.contents[0].uri == AnyUrl("foobar://test-resource")
    assert isinstance(response.contents[0], TextResourceContents)
    assert response.contents[0].text == "Read test-resource"


@pytest.mark.anyio
async def test_streamable_http_client_tool_invocation(initialized_client_session: ClientSession):
    """Test client tool invocation."""
    # First list tools
    tools = await initialized_client_session.list_tools()
    assert len(tools.tools) == 10
    assert tools.tools[0].name == "test_tool"

    # Call the tool
    result = await initialized_client_session.call_tool("test_tool", {})
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert result.content[0].text == "Called test_tool"


@pytest.mark.anyio
async def test_streamable_http_client_error_handling(initialized_client_session: ClientSession):
    """Test error handling in client."""
    with pytest.raises(McpError) as exc_info:
        await initialized_client_session.read_resource(uri=AnyUrl("unknown://test-error"))
    assert exc_info.value.error.code == 0
    assert "Unknown resource: unknown://test-error" in exc_info.value.error.message


@pytest.mark.anyio
async def test_streamable_http_client_session_persistence(basic_server: None, basic_server_url: str):
    """Test that session ID persists across requests."""
    async with streamable_http_client(f"{basic_server_url}/mcp") as (
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
            assert len(tools.tools) == 10

            # Read a resource
            resource = await session.read_resource(uri=AnyUrl("foobar://test-persist"))
            assert isinstance(resource.contents[0], TextResourceContents) is True
            content = resource.contents[0]
            assert isinstance(content, TextResourceContents)
            assert content.text == "Read test-persist"


@pytest.mark.anyio
async def test_streamable_http_client_json_response(json_response_server: None, json_server_url: str):
    """Test client with JSON response mode."""
    async with streamable_http_client(f"{json_server_url}/mcp") as (
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
            assert len(tools.tools) == 10

            # Call a tool and verify JSON response handling
            result = await session.call_tool("test_tool", {})
            assert len(result.content) == 1
            assert result.content[0].type == "text"
            assert result.content[0].text == "Called test_tool"


@pytest.mark.anyio
async def test_streamable_http_client_get_stream(basic_server: None, basic_server_url: str):
    """Test GET stream functionality for server-initiated messages."""
    import mcp.types as types

    notifications_received: list[types.ServerNotification] = []

    # Define message handler to capture notifications
    async def message_handler(  # pragma: no branch
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, types.ServerNotification):  # pragma: no branch
            notifications_received.append(message)

    async with streamable_http_client(f"{basic_server_url}/mcp") as (
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
                if isinstance(notif.root, types.ResourceUpdatedNotification):  # pragma: no branch
                    assert str(notif.root.params.uri) == "http://test_resource/"
                    resource_update_found = True

            assert resource_update_found, "ResourceUpdatedNotification not received via GET stream"


@pytest.mark.anyio
async def test_streamable_http_client_session_termination(basic_server: None, basic_server_url: str):
    """Test client session termination functionality."""

    captured_session_id = None

    # Create the streamable_http_client with a custom httpx client to capture headers
    async with streamable_http_client(f"{basic_server_url}/mcp") as (
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
            assert len(tools.tools) == 10

    headers: dict[str, str] = {}  # pragma: no cover
    if captured_session_id:  # pragma: no cover
        headers[MCP_SESSION_ID_HEADER] = captured_session_id

    async with create_mcp_http_client(headers=headers) as httpx_client:
        async with streamable_http_client(f"{basic_server_url}/mcp", http_client=httpx_client) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                # Attempt to make a request after termination
                with pytest.raises(  # pragma: no branch
                    McpError,
                    match="Session terminated",
                ):
                    await session.list_tools()


@pytest.mark.anyio
async def test_streamable_http_client_session_termination_204(
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

    # Create the streamable_http_client with a custom httpx client to capture headers
    async with streamable_http_client(f"{basic_server_url}/mcp") as (
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
            assert len(tools.tools) == 10

    headers: dict[str, str] = {}  # pragma: no cover
    if captured_session_id:  # pragma: no cover
        headers[MCP_SESSION_ID_HEADER] = captured_session_id

    async with create_mcp_http_client(headers=headers) as httpx_client:
        async with streamable_http_client(f"{basic_server_url}/mcp", http_client=httpx_client) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                # Attempt to make a request after termination
                with pytest.raises(  # pragma: no branch
                    McpError,
                    match="Session terminated",
                ):
                    await session.list_tools()


@pytest.mark.anyio
async def test_streamable_http_client_resumption(event_server: tuple[SimpleEventStore, str]):
    """Test client session resumption using sync primitives for reliable coordination."""
    _, server_url = event_server

    # Variables to track the state
    captured_session_id = None
    captured_resumption_token = None
    captured_notifications: list[types.ServerNotification] = []
    captured_protocol_version = None
    first_notification_received = False

    async def message_handler(  # pragma: no branch
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, types.ServerNotification):  # pragma: no branch
            captured_notifications.append(message)
            # Look for our first notification
            if isinstance(message.root, types.LoggingMessageNotification):  # pragma: no branch
                if message.root.params.data == "First notification before lock":
                    nonlocal first_notification_received
                    first_notification_received = True

    async def on_resumption_token_update(token: str) -> None:
        nonlocal captured_resumption_token
        captured_resumption_token = token

    # First, start the client session and begin the tool that waits on lock
    async with streamable_http_client(f"{server_url}/mcp", terminate_on_close=False) as (
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
    assert len(captured_notifications) == 1  # pragma: no cover
    assert isinstance(captured_notifications[0].root, types.LoggingMessageNotification)  # pragma: no cover
    assert captured_notifications[0].root.params.data == "First notification before lock"  # pragma: no cover

    # Clear notifications for the second phase
    captured_notifications = []  # pragma: no cover

    # Now resume the session with the same mcp-session-id and protocol version
    headers: dict[str, Any] = {}  # pragma: no cover
    if captured_session_id:  # pragma: no cover
        headers[MCP_SESSION_ID_HEADER] = captured_session_id
    if captured_protocol_version:  # pragma: no cover
        headers[MCP_PROTOCOL_VERSION_HEADER] = captured_protocol_version

    async with create_mcp_http_client(headers=headers) as httpx_client:
        async with streamable_http_client(f"{server_url}/mcp", http_client=httpx_client) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream, message_handler=message_handler) as session:
                result = await session.send_request(
                    types.ClientRequest(
                        types.CallToolRequest(
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

            assert isinstance(captured_notifications[0].root, types.LoggingMessageNotification)  # pragma: no cover
            assert captured_notifications[0].root.params.data == "Second notification after lock"  # pragma: no cover


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
        msg_content = params.messages[0].content_as_list[0]
        message_received = msg_content.text if msg_content.type == "text" else None

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
    async with streamable_http_client(f"{basic_server_url}/mcp") as (
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
class ContextAwareServerTest(Server):  # pragma: no cover
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
def run_context_aware_server(port: int):  # pragma: no cover
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
    wait_for_server(basic_server_port)

    yield

    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():  # pragma: no cover
        print("Context-aware server process failed to terminate")


@pytest.mark.anyio
async def test_streamablehttp_request_context_propagation(context_aware_server: None, basic_server_url: str) -> None:
    """Test that request context is properly propagated through StreamableHTTP."""
    custom_headers = {
        "Authorization": "Bearer test-token",
        "X-Custom-Header": "test-value",
        "X-Trace-Id": "trace-123",
    }

    async with create_mcp_http_client(headers=custom_headers) as httpx_client:
        async with streamable_http_client(f"{basic_server_url}/mcp", http_client=httpx_client) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
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

        async with create_mcp_http_client(headers=headers) as httpx_client:
            async with streamable_http_client(f"{basic_server_url}/mcp", http_client=httpx_client) as (
                read_stream,
                write_stream,
                _,
            ):
                async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                    await session.initialize()

                    # Call the tool that echoes context
                    tool_result = await session.call_tool("echo_context", {"request_id": f"request-{i}"})

                    assert len(tool_result.content) == 1
                    assert isinstance(tool_result.content[0], TextContent)
                    context_data = json.loads(tool_result.content[0].text)
                    contexts.append(context_data)

    # Verify each request had its own context
    assert len(contexts) == 3  # pragma: no cover
    for i, ctx in enumerate(contexts):  # pragma: no cover
        assert ctx["request_id"] == f"request-{i}"
        assert ctx["headers"].get("x-request-id") == f"request-{i}"
        assert ctx["headers"].get("x-custom-value") == f"value-{i}"
        assert ctx["headers"].get("authorization") == f"Bearer token-{i}"


@pytest.mark.anyio
async def test_client_includes_protocol_version_header_after_init(context_aware_server: None, basic_server_url: str):
    """Test that client includes mcp-protocol-version header after initialization."""
    async with streamable_http_client(f"{basic_server_url}/mcp") as (
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
        async with streamable_http_client(f"{basic_server_url}/mcp") as (
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
    async with streamable_http_client(f"{basic_server_url}/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            tools = await session.list_tools()
            assert tools.tools


@pytest.mark.anyio
async def test_handle_sse_event_skips_empty_data():
    """Test that _handle_sse_event skips empty SSE data (keep-alive pings)."""
    transport = StreamableHTTPTransport(url="http://localhost:8000/mcp")

    # Create a mock SSE event with empty data (keep-alive ping)
    mock_sse = ServerSentEvent(event="message", data="", id=None, retry=None)

    # Create a mock stream writer
    write_stream, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](1)

    try:
        # Call _handle_sse_event with empty data - should return False and not raise
        result = await transport._handle_sse_event(mock_sse, write_stream)

        # Should return False (not complete) for empty data
        assert result is False

        # Nothing should have been written to the stream
        # Check buffer is empty (statistics().current_buffer_used returns buffer size)
        assert write_stream.statistics().current_buffer_used == 0
    finally:
        await write_stream.aclose()
        await read_stream.aclose()


@pytest.mark.anyio
async def test_priming_event_not_sent_for_old_protocol_version():
    """Test that _maybe_send_priming_event skips for old protocol versions (backwards compat)."""
    # Create a transport with an event store
    transport = StreamableHTTPServerTransport(
        "/mcp",
        event_store=SimpleEventStore(),
    )

    # Create a mock stream writer
    write_stream, read_stream = anyio.create_memory_object_stream[dict[str, Any]](1)

    try:
        # Call _maybe_send_priming_event with OLD protocol version - should NOT send
        await transport._maybe_send_priming_event("test-request-id", write_stream, "2025-06-18")

        # Nothing should have been written to the stream
        assert write_stream.statistics().current_buffer_used == 0

        # Now test with NEW protocol version - should send
        await transport._maybe_send_priming_event("test-request-id-2", write_stream, "2025-11-25")

        # Should have written a priming event
        assert write_stream.statistics().current_buffer_used == 1
    finally:
        await write_stream.aclose()
        await read_stream.aclose()


@pytest.mark.anyio
async def test_priming_event_not_sent_without_event_store():
    """Test that _maybe_send_priming_event returns early when no event_store is configured."""
    # Create a transport WITHOUT an event store
    transport = StreamableHTTPServerTransport("/mcp")

    # Create a mock stream writer
    write_stream, read_stream = anyio.create_memory_object_stream[dict[str, Any]](1)

    try:
        # Call _maybe_send_priming_event - should return early without sending
        await transport._maybe_send_priming_event("test-request-id", write_stream, "2025-11-25")

        # Nothing should have been written to the stream
        assert write_stream.statistics().current_buffer_used == 0
    finally:
        await write_stream.aclose()
        await read_stream.aclose()


@pytest.mark.anyio
async def test_priming_event_includes_retry_interval():
    """Test that _maybe_send_priming_event includes retry field when retry_interval is set."""
    # Create a transport with an event store AND retry_interval
    transport = StreamableHTTPServerTransport(
        "/mcp",
        event_store=SimpleEventStore(),
        retry_interval=5000,
    )

    # Create a mock stream writer
    write_stream, read_stream = anyio.create_memory_object_stream[dict[str, Any]](1)

    try:
        # Call _maybe_send_priming_event with new protocol version
        await transport._maybe_send_priming_event("test-request-id", write_stream, "2025-11-25")

        # Should have written a priming event with retry field
        assert write_stream.statistics().current_buffer_used == 1

        # Read the event and verify it has retry field
        event = await read_stream.receive()
        assert "retry" in event
        assert event["retry"] == 5000
    finally:
        await write_stream.aclose()
        await read_stream.aclose()


@pytest.mark.anyio
async def test_close_sse_stream_callback_not_provided_for_old_protocol_version():
    """Test that close_sse_stream callbacks are NOT provided for old protocol versions."""
    # Create a transport with an event store
    transport = StreamableHTTPServerTransport(
        "/mcp",
        event_store=SimpleEventStore(),
    )

    # Create a mock message and request
    mock_message = JSONRPCMessage(root=JSONRPCRequest(jsonrpc="2.0", id="test-1", method="tools/list"))
    mock_request = MagicMock()

    # Call _create_session_message with OLD protocol version
    session_msg = transport._create_session_message(mock_message, mock_request, "test-request-id", "2025-06-18")

    # Callbacks should NOT be provided for old protocol version
    assert session_msg.metadata is not None
    assert isinstance(session_msg.metadata, ServerMessageMetadata)
    assert session_msg.metadata.close_sse_stream is None
    assert session_msg.metadata.close_standalone_sse_stream is None

    # Now test with NEW protocol version - should provide callbacks
    session_msg_new = transport._create_session_message(mock_message, mock_request, "test-request-id-2", "2025-11-25")

    # Callbacks SHOULD be provided for new protocol version
    assert session_msg_new.metadata is not None
    assert isinstance(session_msg_new.metadata, ServerMessageMetadata)
    assert session_msg_new.metadata.close_sse_stream is not None
    assert session_msg_new.metadata.close_standalone_sse_stream is not None


@pytest.mark.anyio
async def test_streamable_http_client_receives_priming_event(
    event_server: tuple[SimpleEventStore, str],
) -> None:
    """Client should receive priming event (resumption token update) on POST SSE stream."""
    _, server_url = event_server

    captured_resumption_tokens: list[str] = []

    async def on_resumption_token_update(token: str) -> None:
        captured_resumption_tokens.append(token)

    async with streamable_http_client(f"{server_url}/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Call tool with resumption token callback via send_request
            metadata = ClientMessageMetadata(
                on_resumption_token_update=on_resumption_token_update,
            )
            result = await session.send_request(
                types.ClientRequest(
                    types.CallToolRequest(
                        params=types.CallToolRequestParams(name="test_tool", arguments={}),
                    )
                ),
                types.CallToolResult,
                metadata=metadata,
            )
            assert result is not None

            # Should have received priming event token BEFORE response data
            # Priming event = 1 token (empty data, id only)
            # Response = 1 token (actual JSON-RPC response)
            # Total = 2 tokens minimum
            assert len(captured_resumption_tokens) >= 2, (
                f"Server must send priming event before response. "
                f"Expected >= 2 tokens (priming + response), got {len(captured_resumption_tokens)}"
            )
            assert captured_resumption_tokens[0] is not None


@pytest.mark.anyio
async def test_server_close_sse_stream_via_context(
    event_server: tuple[SimpleEventStore, str],
) -> None:
    """Server tool can call ctx.close_sse_stream() to close connection."""
    _, server_url = event_server

    async with streamable_http_client(f"{server_url}/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Call tool that closes stream mid-operation
            # This should NOT raise NotImplementedError when fully implemented
            result = await session.call_tool("tool_with_stream_close", {})

            # Client should still receive complete response (via auto-reconnect)
            assert result is not None
            assert len(result.content) > 0
            assert result.content[0].type == "text"
            assert isinstance(result.content[0], TextContent)
            assert result.content[0].text == "Done"


@pytest.mark.anyio
async def test_streamable_http_client_auto_reconnects(
    event_server: tuple[SimpleEventStore, str],
) -> None:
    """Client should auto-reconnect with Last-Event-ID when server closes after priming event."""
    _, server_url = event_server
    captured_notifications: list[str] = []

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):  # pragma: no branch
            return  # pragma: no cover
        if isinstance(message, types.ServerNotification):  # pragma: no branch
            if isinstance(message.root, types.LoggingMessageNotification):  # pragma: no branch
                captured_notifications.append(str(message.root.params.data))

    async with streamable_http_client(f"{server_url}/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
            message_handler=message_handler,
        ) as session:
            await session.initialize()

            # Call tool that:
            # 1. Sends notification
            # 2. Closes SSE stream
            # 3. Sends more notifications (stored in event_store)
            # 4. Returns response
            result = await session.call_tool("tool_with_stream_close", {})

            # Client should have auto-reconnected and received ALL notifications
            assert len(captured_notifications) >= 2, (
                "Client should auto-reconnect and receive notifications sent both before and after stream close"
            )
            assert result.content[0].type == "text"
            assert isinstance(result.content[0], TextContent)
            assert result.content[0].text == "Done"


@pytest.mark.anyio
async def test_streamable_http_client_respects_retry_interval(
    event_server: tuple[SimpleEventStore, str],
) -> None:
    """Client MUST respect retry field, waiting specified ms before reconnecting."""
    _, server_url = event_server

    async with streamable_http_client(f"{server_url}/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            start_time = time.monotonic()
            result = await session.call_tool("tool_with_stream_close", {})
            elapsed = time.monotonic() - start_time

            # Verify result was received
            assert result.content[0].type == "text"
            assert isinstance(result.content[0], TextContent)
            assert result.content[0].text == "Done"

            # The elapsed time should include at least the retry interval
            # if reconnection occurred. This test may be flaky depending on
            # implementation details, but demonstrates the expected behavior.
            # Note: This assertion may need adjustment based on actual implementation
            assert elapsed >= 0.4, f"Client should wait ~500ms before reconnecting, but elapsed time was {elapsed:.3f}s"


@pytest.mark.anyio
async def test_streamable_http_sse_polling_full_cycle(
    event_server: tuple[SimpleEventStore, str],
) -> None:
    """End-to-end test: server closes stream, client reconnects, receives all events."""
    _, server_url = event_server
    all_notifications: list[str] = []

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):  # pragma: no branch
            return  # pragma: no cover
        if isinstance(message, types.ServerNotification):  # pragma: no branch
            if isinstance(message.root, types.LoggingMessageNotification):  # pragma: no branch
                all_notifications.append(str(message.root.params.data))

    async with streamable_http_client(f"{server_url}/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
            message_handler=message_handler,
        ) as session:
            await session.initialize()

            # Call tool that simulates polling pattern:
            # 1. Server sends priming event
            # 2. Server sends "Before close" notification
            # 3. Server closes stream (calls close_sse_stream)
            # 4. (client reconnects automatically)
            # 5. Server sends "After close" notification
            # 6. Server sends final response
            result = await session.call_tool("tool_with_stream_close", {})

            # Verify all notifications received in order
            assert "Before close" in all_notifications, "Should receive notification sent before stream close"
            assert "After close" in all_notifications, (
                "Should receive notification sent after stream close (via auto-reconnect)"
            )
            assert result.content[0].type == "text"
            assert isinstance(result.content[0], TextContent)
            assert result.content[0].text == "Done"


@pytest.mark.anyio
async def test_streamable_http_events_replayed_after_disconnect(
    event_server: tuple[SimpleEventStore, str],
) -> None:
    """Events sent while client is disconnected should be replayed on reconnect."""
    _, server_url = event_server
    notification_data: list[str] = []

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):  # pragma: no branch
            return  # pragma: no cover
        if isinstance(message, types.ServerNotification):  # pragma: no branch
            if isinstance(message.root, types.LoggingMessageNotification):  # pragma: no branch
                notification_data.append(str(message.root.params.data))

    async with streamable_http_client(f"{server_url}/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
            message_handler=message_handler,
        ) as session:
            await session.initialize()

            # Tool sends: notification1, close_stream, notification2, notification3, response
            # Client should receive all notifications even though 2&3 were sent during disconnect
            result = await session.call_tool("tool_with_multiple_notifications_and_close", {})

            assert "notification1" in notification_data, "Should receive notification1 (sent before close)"
            assert "notification2" in notification_data, "Should receive notification2 (sent after close, replayed)"
            assert "notification3" in notification_data, "Should receive notification3 (sent after close, replayed)"

            # Verify order: notification1 should come before notification2 and notification3
            idx1 = notification_data.index("notification1")
            idx2 = notification_data.index("notification2")
            idx3 = notification_data.index("notification3")
            assert idx1 < idx2 < idx3, "Notifications should be received in order"

            assert result.content[0].type == "text"
            assert isinstance(result.content[0], TextContent)
            assert result.content[0].text == "All notifications sent"


@pytest.mark.anyio
async def test_streamable_http_multiple_reconnections(
    event_server: tuple[SimpleEventStore, str],
):
    """Verify multiple close_sse_stream() calls each trigger a client reconnect.

    Server uses retry_interval=500ms, tool sleeps 600ms after each close to ensure
    client has time to reconnect before the next checkpoint.

    With 3 checkpoints, we expect 8 resumption tokens:
    - 1 priming (initial POST connection)
    - 3 notifications (checkpoint_0, checkpoint_1, checkpoint_2)
    - 3 priming (one per reconnect after each close)
    - 1 response
    """
    _, server_url = event_server
    resumption_tokens: list[str] = []

    async def on_resumption_token(token: str) -> None:
        resumption_tokens.append(token)

    async with streamable_http_client(f"{server_url}/mcp") as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Use send_request with metadata to track resumption tokens
            metadata = ClientMessageMetadata(on_resumption_token_update=on_resumption_token)
            result = await session.send_request(
                types.ClientRequest(
                    types.CallToolRequest(
                        method="tools/call",
                        params=types.CallToolRequestParams(
                            name="tool_with_multiple_stream_closes",
                            # retry_interval=500ms, so sleep 600ms to ensure reconnect completes
                            arguments={"checkpoints": 3, "sleep_time": 0.6},
                        ),
                    )
                ),
                types.CallToolResult,
                metadata=metadata,
            )

            assert result.content[0].type == "text"
            assert isinstance(result.content[0], TextContent)
            assert "Completed 3 checkpoints" in result.content[0].text

    # 4 priming + 3 notifications + 1 response = 8 tokens
    assert len(resumption_tokens) == 8, (  # pragma: no cover
        f"Expected 8 resumption tokens (4 priming + 3 notifs + 1 response), "
        f"got {len(resumption_tokens)}: {resumption_tokens}"
    )


@pytest.mark.anyio
async def test_standalone_get_stream_reconnection(
    event_server: tuple[SimpleEventStore, str],
) -> None:
    """
    Test that standalone GET stream automatically reconnects after server closes it.

    Verifies:
    1. Client receives notification 1 via GET stream
    2. Server closes GET stream
    3. Client reconnects with Last-Event-ID
    4. Client receives notification 2 on new connection

    Note: Requires event_server fixture (with event store) because close_standalone_sse_stream
    callback is only provided when event_store is configured and protocol version >= 2025-11-25.
    """
    _, server_url = event_server
    received_notifications: list[str] = []

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):
            return  # pragma: no cover
        if isinstance(message, types.ServerNotification):  # pragma: no branch
            if isinstance(message.root, types.ResourceUpdatedNotification):  # pragma: no branch
                received_notifications.append(str(message.root.params.uri))

    async with streamable_http_client(f"{server_url}/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
            message_handler=message_handler,
        ) as session:
            await session.initialize()

            # Call tool that:
            # 1. Sends notification_1 via GET stream
            # 2. Closes standalone GET stream
            # 3. Sends notification_2 (stored in event_store)
            # 4. Returns response
            result = await session.call_tool("tool_with_standalone_stream_close", {})

            # Verify the tool completed
            assert result.content[0].type == "text"
            assert isinstance(result.content[0], TextContent)
            assert result.content[0].text == "Standalone stream close test done"

            # Verify both notifications were received
            assert "http://notification_1/" in received_notifications, (
                f"Should receive notification 1 (sent before GET stream close), got: {received_notifications}"
            )
            assert "http://notification_2/" in received_notifications, (
                f"Should receive notification 2 after reconnect, got: {received_notifications}"
            )


@pytest.mark.anyio
async def test_streamable_http_client_does_not_mutate_provided_client(
    basic_server: None, basic_server_url: str
) -> None:
    """Test that streamable_http_client does not mutate the provided httpx client's headers."""
    # Create a client with custom headers
    original_headers = {
        "X-Custom-Header": "custom-value",
        "Authorization": "Bearer test-token",
    }

    async with httpx.AsyncClient(headers=original_headers, follow_redirects=True) as custom_client:
        # Use the client with streamable_http_client
        async with streamable_http_client(f"{basic_server_url}/mcp", http_client=custom_client) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                result = await session.initialize()
                assert isinstance(result, InitializeResult)

        # Verify client headers were not mutated with MCP protocol headers
        # If accept header exists, it should still be httpx default, not MCP's
        if "accept" in custom_client.headers:  # pragma: no branch
            assert custom_client.headers.get("accept") == "*/*"
        # MCP content-type should not have been added
        assert custom_client.headers.get("content-type") != "application/json"

        # Verify custom headers are still present and unchanged
        assert custom_client.headers.get("X-Custom-Header") == "custom-value"
        assert custom_client.headers.get("Authorization") == "Bearer test-token"


@pytest.mark.anyio
async def test_streamable_http_client_mcp_headers_override_defaults(
    context_aware_server: None, basic_server_url: str
) -> None:
    """Test that MCP protocol headers override httpx.AsyncClient default headers."""
    # httpx.AsyncClient has default "accept: */*" header
    # We need to verify that our MCP accept header overrides it in actual requests

    async with httpx.AsyncClient(follow_redirects=True) as client:
        # Verify client has default accept header
        assert client.headers.get("accept") == "*/*"

        async with streamable_http_client(f"{basic_server_url}/mcp", http_client=client) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()

                # Use echo_headers tool to see what headers the server actually received
                tool_result = await session.call_tool("echo_headers", {})
                assert len(tool_result.content) == 1
                assert isinstance(tool_result.content[0], TextContent)
                headers_data = json.loads(tool_result.content[0].text)

                # Verify MCP protocol headers were sent (not httpx defaults)
                assert "accept" in headers_data
                assert "application/json" in headers_data["accept"]
                assert "text/event-stream" in headers_data["accept"]

                assert "content-type" in headers_data
                assert headers_data["content-type"] == "application/json"


@pytest.mark.anyio
async def test_streamable_http_client_preserves_custom_with_mcp_headers(
    context_aware_server: None, basic_server_url: str
) -> None:
    """Test that both custom headers and MCP protocol headers are sent in requests."""
    custom_headers = {
        "X-Custom-Header": "custom-value",
        "X-Request-Id": "req-123",
        "Authorization": "Bearer test-token",
    }

    async with httpx.AsyncClient(headers=custom_headers, follow_redirects=True) as client:
        async with streamable_http_client(f"{basic_server_url}/mcp", http_client=client) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()

                # Use echo_headers tool to verify both custom and MCP headers are present
                tool_result = await session.call_tool("echo_headers", {})
                assert len(tool_result.content) == 1
                assert isinstance(tool_result.content[0], TextContent)
                headers_data = json.loads(tool_result.content[0].text)

                # Verify custom headers are present
                assert headers_data.get("x-custom-header") == "custom-value"
                assert headers_data.get("x-request-id") == "req-123"
                assert headers_data.get("authorization") == "Bearer test-token"

                # Verify MCP protocol headers are also present
                assert "accept" in headers_data
                assert "application/json" in headers_data["accept"]
                assert "text/event-stream" in headers_data["accept"]

                assert "content-type" in headers_data
                assert headers_data["content-type"] == "application/json"


@pytest.mark.anyio
async def test_streamable_http_transport_deprecated_params_ignored(basic_server: None, basic_server_url: str) -> None:
    """Test that deprecated parameters passed to StreamableHTTPTransport are properly ignored."""
    with pytest.warns(DeprecationWarning):
        transport = StreamableHTTPTransport(  # pyright: ignore[reportDeprecated]
            url=f"{basic_server_url}/mcp",
            headers={"X-Should-Be-Ignored": "ignored"},
            timeout=999,
            sse_read_timeout=timedelta(seconds=999),
            auth=None,
        )

    headers = transport._prepare_headers()
    assert "X-Should-Be-Ignored" not in headers
    assert headers["accept"] == "application/json, text/event-stream"
    assert headers["content-type"] == "application/json"


@pytest.mark.anyio
async def test_streamablehttp_client_deprecation_warning(basic_server: None, basic_server_url: str) -> None:
    """Test that the old streamablehttp_client() function issues a deprecation warning."""
    with pytest.warns(DeprecationWarning, match="Use `streamable_http_client` instead"):
        async with streamablehttp_client(f"{basic_server_url}/mcp") as (  # pyright: ignore[reportDeprecated]
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()
                tools = await session.list_tools()
                assert len(tools.tools) > 0
