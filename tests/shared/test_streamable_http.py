"""Tests for the StreamableHTTP server and client transport.

Contains tests for both server and client sides of the StreamableHTTP transport, driven
entirely in process.
"""

from __future__ import annotations as _annotations

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import urlparse

import anyio
import httpx
import pytest
from httpx_sse import ServerSentEvent
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount

from mcp import MCPError, types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import StreamableHTTPTransport, streamable_http_client
from mcp.server import Server, ServerRequestContext
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
from mcp.shared._context import RequestContext
from mcp.shared._context_streams import create_context_streams
from mcp.shared.message import ClientMessageMetadata, ServerMessageMetadata, SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    InitializeResult,
    JSONRPCRequest,
    ListToolsResult,
    PaginatedRequestParams,
    ReadResourceRequestParams,
    ReadResourceResult,
    TextContent,
    TextResourceContents,
    Tool,
)
from tests.interaction.transports import StreamingASGITransport

# Test constants
SERVER_NAME = "test_streamable_http_server"
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

# The in-process app is mounted at this origin purely so URLs are well-formed; nothing listens here.
BASE_URL = "http://127.0.0.1:8000"


# Helper functions
def extract_protocol_version_from_sse(response: httpx.Response) -> str:
    """Extract the negotiated protocol version from an SSE initialization response."""
    assert response.headers.get("Content-Type") == "text/event-stream"
    for line in response.text.splitlines():
        if line.startswith("data: "):
            init_data = json.loads(line[6:])
            return init_data["result"]["protocolVersion"]
    raise ValueError("Could not extract protocol version from SSE response")  # pragma: no cover


# Simple in-memory event store for testing
class SimpleEventStore(EventStore):
    """Simple in-memory event store for testing."""

    def __init__(self):
        self._events: list[tuple[StreamId, EventId, types.JSONRPCMessage | None]] = []
        self._event_id_counter = 0

    async def store_event(self, stream_id: StreamId, message: types.JSONRPCMessage | None) -> EventId:
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
        # Find the stream ID of the last event; clients always resume from a stored event.
        target_stream_id = next(stream_id for stream_id, event_id, _ in self._events if event_id == last_event_id)

        # Convert last_event_id to int for comparison
        last_event_id_int = int(last_event_id)

        # Replay only events from the same stream with ID > last_event_id, skipping priming
        # events (None message).
        for stream_id, event_id, message in self._events:
            if stream_id == target_stream_id and message is not None and int(event_id) > last_event_id_int:
                await send_callback(EventMessage(message, event_id))

        return target_stream_id


@dataclass
class ServerState:
    lock: anyio.Event = field(default_factory=anyio.Event)


@asynccontextmanager
async def _server_lifespan(_server: Server[ServerState]) -> AsyncIterator[ServerState]:
    yield ServerState()


async def _handle_read_resource(
    ctx: ServerRequestContext[ServerState], params: ReadResourceRequestParams
) -> ReadResourceResult:
    uri = str(params.uri)
    parsed = urlparse(uri)
    if parsed.scheme == "foobar":
        return ReadResourceResult(
            contents=[TextResourceContents(uri=uri, text=f"Read {parsed.netloc}", mime_type="text/plain")]
        )
    raise ValueError(f"Unknown resource: {uri}")


async def _handle_list_tools(
    ctx: ServerRequestContext[ServerState], params: PaginatedRequestParams | None
) -> ListToolsResult:
    return ListToolsResult(
        tools=[
            Tool(
                name="test_tool",
                description="A test tool",
                input_schema={"type": "object", "properties": {}},
            ),
            Tool(
                name="test_tool_with_standalone_notification",
                description="A test tool that sends a notification",
                input_schema={"type": "object", "properties": {}},
            ),
            Tool(
                name="test_sampling_tool",
                description="A tool that triggers server-side sampling",
                input_schema={"type": "object", "properties": {}},
            ),
            Tool(
                name="wait_for_lock_with_notification",
                description="A tool that sends a notification and waits for lock",
                input_schema={"type": "object", "properties": {}},
            ),
            Tool(
                name="release_lock",
                description="A tool that releases the lock",
                input_schema={"type": "object", "properties": {}},
            ),
            Tool(
                name="tool_with_stream_close",
                description="A tool that closes SSE stream mid-operation",
                input_schema={"type": "object", "properties": {}},
            ),
            Tool(
                name="tool_with_multiple_notifications_and_close",
                description="Tool that sends notification1, closes stream, sends notification2, notification3",
                input_schema={"type": "object", "properties": {}},
            ),
            Tool(
                name="tool_with_standalone_stream_close",
                description="Tool that closes standalone GET stream mid-operation",
                input_schema={"type": "object", "properties": {}},
            ),
        ]
    )


async def _handle_call_tool(ctx: ServerRequestContext[ServerState], params: CallToolRequestParams) -> CallToolResult:
    name = params.name

    # When the tool is called, send a notification to test GET stream
    if name == "test_tool_with_standalone_notification":
        await ctx.session.send_resource_updated(uri="http://test_resource")
        return CallToolResult(content=[TextContent(type="text", text=f"Called {name}")])

    elif name == "test_sampling_tool":
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

        assert sampling_result.content.type == "text"
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"Response from sampling: {sampling_result.content.text}",
                )
            ]
        )

    elif name == "wait_for_lock_with_notification":
        await ctx.session.send_log_message(
            level="info",
            data="First notification before lock",
            logger="lock_tool",
            related_request_id=ctx.request_id,
        )

        await ctx.lifespan_context.lock.wait()

        await ctx.session.send_log_message(
            level="info",
            data="Second notification after lock",
            logger="lock_tool",
            related_request_id=ctx.request_id,
        )

        return CallToolResult(content=[TextContent(type="text", text="Completed")])

    elif name == "release_lock":
        ctx.lifespan_context.lock.set()
        return CallToolResult(content=[TextContent(type="text", text="Lock released")])

    elif name == "tool_with_stream_close":
        await ctx.session.send_log_message(
            level="info",
            data="Before close",
            logger="stream_close_tool",
            related_request_id=ctx.request_id,
        )
        assert ctx.close_sse_stream is not None
        await ctx.close_sse_stream()
        await anyio.sleep(0.1)
        await ctx.session.send_log_message(
            level="info",
            data="After close",
            logger="stream_close_tool",
            related_request_id=ctx.request_id,
        )
        return CallToolResult(content=[TextContent(type="text", text="Done")])

    elif name == "tool_with_multiple_notifications_and_close":
        await ctx.session.send_log_message(
            level="info",
            data="notification1",
            logger="multi_notif_tool",
            related_request_id=ctx.request_id,
        )
        assert ctx.close_sse_stream is not None
        await ctx.close_sse_stream()
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
        return CallToolResult(content=[TextContent(type="text", text="All notifications sent")])

    elif name == "tool_with_standalone_stream_close":
        await ctx.session.send_resource_updated(uri="http://notification_1")
        await anyio.sleep(0.1)

        assert ctx.close_standalone_sse_stream is not None
        await ctx.close_standalone_sse_stream()

        await anyio.sleep(1.5)
        await ctx.session.send_resource_updated(uri="http://notification_2")

        return CallToolResult(content=[TextContent(type="text", text="Standalone stream close test done")])

    return CallToolResult(content=[TextContent(type="text", text=f"Called {name}")])


def _create_server() -> Server[ServerState]:
    return Server(
        SERVER_NAME,
        lifespan=_server_lifespan,
        on_read_resource=_handle_read_resource,
        on_list_tools=_handle_list_tools,
        on_call_tool=_handle_call_tool,
    )


@asynccontextmanager
async def running_app(
    is_json_response_enabled: bool = False,
    event_store: EventStore | None = None,
    retry_interval: int | None = None,
    server: Server[Any] | None = None,
) -> AsyncIterator[Starlette]:
    """Serve the test server's streamable HTTP app in process for the duration.

    Args:
        is_json_response_enabled: If True, use JSON responses instead of SSE streams.
        event_store: Optional event store for testing resumability.
        retry_interval: Retry interval in milliseconds for SSE polling.
        server: Server to mount; defaults to the file's shared test server.
    """
    # DNS-rebinding protection validates Host/Origin headers against a network attack that cannot
    # exist for an in-process app; the protection itself is pinned by
    # tests/server/test_streamable_http_security.py.
    session_manager = StreamableHTTPSessionManager(
        app=server if server is not None else _create_server(),
        event_store=event_store,
        json_response=is_json_response_enabled,
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        retry_interval=retry_interval,
    )
    app = Starlette(routes=[Mount("/mcp", app=session_manager.handle_request)])
    async with session_manager.run():
        yield app


def make_client(app: Starlette, headers: dict[str, str] | None = None) -> httpx.AsyncClient:
    """An httpx client served in process by `app`, with create_mcp_http_client's redirect default.

    (Starlette's Mount 307-redirects the bare /mcp path to /mcp/, which the SDK's own client
    factory follows.)
    """
    return httpx.AsyncClient(
        transport=StreamingASGITransport(app), base_url=BASE_URL, headers=headers, follow_redirects=True
    )


# Test fixtures
@pytest.fixture
async def basic_app() -> AsyncIterator[Starlette]:
    """The test server's app with SSE response mode."""
    async with running_app() as app:
        yield app


@pytest.fixture
async def json_app() -> AsyncIterator[Starlette]:
    """The test server's app with JSON response mode."""
    async with running_app(is_json_response_enabled=True) as app:
        yield app


@pytest.fixture
def event_store() -> SimpleEventStore:
    """Create a test event store."""
    return SimpleEventStore()


@pytest.fixture
async def event_app(event_store: SimpleEventStore) -> AsyncIterator[tuple[SimpleEventStore, Starlette]]:
    """The test server's app with an event store and retry_interval enabled."""
    async with running_app(event_store=event_store, retry_interval=500) as app:
        yield event_store, app


# Basic request validation tests
@pytest.mark.anyio
async def test_accept_header_validation(basic_app: Starlette) -> None:
    """A POST without an Accept header is rejected with 406."""
    async with make_client(basic_app) as client:
        # Suppress the httpx client default Accept: */* header
        del client.headers["accept"]
        response = await client.post(
            "/mcp",
            headers={"Content-Type": "application/json"},
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
        )
        assert response.status_code == 406
        assert "Not Acceptable" in response.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "accept_header",
    [
        "*/*",
        "application/*, text/*",
        "text/*, application/json",
        "application/json, text/*",
        "*/*;q=0.8",
        "application/*;q=0.9, text/*;q=0.8",
    ],
)
async def test_accept_header_wildcard(basic_app: Starlette, accept_header: str) -> None:
    """Wildcard Accept headers are accepted per RFC 7231."""
    async with make_client(basic_app) as client:
        response = await client.post(
            "/mcp",
            headers={
                "Accept": accept_header,
                "Content-Type": "application/json",
            },
            json=INIT_REQUEST,
        )
        assert response.status_code == 200


@pytest.mark.anyio
@pytest.mark.parametrize(
    "accept_header",
    [
        "text/html",
        "application/*",
        "text/*",
    ],
)
async def test_accept_header_incompatible(basic_app: Starlette, accept_header: str) -> None:
    """Accept headers that cannot cover both response representations are rejected for SSE mode."""
    async with make_client(basic_app) as client:
        response = await client.post(
            "/mcp",
            headers={
                "Accept": accept_header,
                "Content-Type": "application/json",
            },
            json=INIT_REQUEST,
        )
        assert response.status_code == 406
        assert "Not Acceptable" in response.text


@pytest.mark.anyio
async def test_content_type_validation(basic_app: Starlette) -> None:
    """A POST whose Content-Type is not application/json is rejected with 400."""
    async with make_client(basic_app) as client:
        response = await client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "text/plain",
            },
            content="This is not JSON",
        )

        assert response.status_code == 400
        assert "Invalid Content-Type" in response.text


@pytest.mark.anyio
async def test_json_validation(basic_app: Starlette) -> None:
    """A POST body that is not valid JSON is rejected with a parse error."""
    async with make_client(basic_app) as client:
        response = await client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            content="this is not valid json",
        )
        assert response.status_code == 400
        assert "Parse error" in response.text


@pytest.mark.anyio
async def test_json_parsing(basic_app: Starlette) -> None:
    """Valid JSON that is not a JSON-RPC message is rejected with a validation error."""
    async with make_client(basic_app) as client:
        response = await client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={"foo": "bar"},
        )
        assert response.status_code == 400
        assert "Validation error" in response.text


@pytest.mark.anyio
async def test_method_not_allowed(basic_app: Starlette) -> None:
    """Unsupported HTTP methods are rejected with 405."""
    async with make_client(basic_app) as client:
        response = await client.put(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
        )
        assert response.status_code == 405
        assert "Method Not Allowed" in response.text


@pytest.mark.anyio
async def test_session_validation(basic_app: Starlette) -> None:
    """A non-initialize request without a session ID is rejected with 400."""
    async with make_client(basic_app) as client:
        response = await client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={"jsonrpc": "2.0", "method": "list_tools", "id": 1},
        )
        assert response.status_code == 400
        assert "Missing session ID" in response.text


def test_session_id_pattern() -> None:
    """SESSION_ID_PATTERN accepts visible ASCII (0x21-0x7E) and rejects everything else."""
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


def test_streamable_http_transport_init_validation() -> None:
    """StreamableHTTPServerTransport accepts valid or absent session IDs and rejects invalid ones."""
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


@pytest.mark.anyio
async def test_session_termination(basic_app: Starlette) -> None:
    """DELETE terminates the session, after which requests for it return 404."""
    async with make_client(basic_app) as client:
        response = await client.post(
            "/mcp",
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
        assert session_id is not None
        response = await client.delete(
            "/mcp",
            headers={
                MCP_SESSION_ID_HEADER: session_id,
                MCP_PROTOCOL_VERSION_HEADER: negotiated_version,
            },
        )
        assert response.status_code == 200

        # Try to use the terminated session
        response = await client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                MCP_SESSION_ID_HEADER: session_id,
            },
            json={"jsonrpc": "2.0", "method": "ping", "id": 2},
        )
        assert response.status_code == 404
        assert "Session has been terminated" in response.text


@pytest.mark.anyio
async def test_response(basic_app: Starlette) -> None:
    """A request on an initialized session is answered on a text/event-stream response."""
    async with make_client(basic_app) as client:
        response = await client.post(
            "/mcp",
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
        assert session_id is not None

        # Try to use the session with proper headers
        async with client.stream(
            "POST",
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                MCP_SESSION_ID_HEADER: session_id,  # Use the session ID we got earlier
                MCP_PROTOCOL_VERSION_HEADER: negotiated_version,
            },
            json={"jsonrpc": "2.0", "method": "tools/list", "id": "tools-1"},
        ) as tools_response:
            assert tools_response.status_code == 200
            assert tools_response.headers.get("Content-Type") == "text/event-stream"


@pytest.mark.anyio
async def test_json_response(json_app: Starlette) -> None:
    """With JSON response mode enabled, requests are answered with application/json bodies."""
    async with make_client(json_app) as client:
        response = await client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json=INIT_REQUEST,
        )
        assert response.status_code == 200
        assert response.headers.get("Content-Type") == "application/json"


@pytest.mark.anyio
async def test_json_response_accept_json_only(json_app: Starlette) -> None:
    """JSON response mode only requires application/json in the Accept header."""
    async with make_client(json_app) as client:
        response = await client.post(
            "/mcp",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=INIT_REQUEST,
        )
        assert response.status_code == 200
        assert response.headers.get("Content-Type") == "application/json"


@pytest.mark.anyio
async def test_json_response_missing_accept_header(json_app: Starlette) -> None:
    """JSON response mode still rejects requests without an Accept header."""
    async with make_client(json_app) as client:
        # Suppress the httpx client default Accept: */* header
        del client.headers["accept"]
        response = await client.post(
            "/mcp",
            headers={
                "Content-Type": "application/json",
            },
            json=INIT_REQUEST,
        )
        assert response.status_code == 406
        assert "Not Acceptable" in response.text


@pytest.mark.anyio
async def test_json_response_incorrect_accept_header(json_app: Starlette) -> None:
    """JSON response mode rejects an Accept header that does not cover application/json."""
    async with make_client(json_app) as client:
        # Test with only text/event-stream (wrong for JSON server)
        response = await client.post(
            "/mcp",
            headers={
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
            },
            json=INIT_REQUEST,
        )
        assert response.status_code == 406
        assert "Not Acceptable" in response.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "accept_header",
    [
        "*/*",
        "application/*",
        "application/*;q=0.9",
    ],
)
async def test_json_response_wildcard_accept_header(json_app: Starlette, accept_header: str) -> None:
    """JSON response mode accepts wildcard Accept headers per RFC 7231."""
    async with make_client(json_app) as client:
        response = await client.post(
            "/mcp",
            headers={
                "Accept": accept_header,
                "Content-Type": "application/json",
            },
            json=INIT_REQUEST,
        )
        assert response.status_code == 200
        assert response.headers.get("Content-Type") == "application/json"


@pytest.mark.anyio
async def test_get_sse_stream(basic_app: Starlette) -> None:
    """GET establishes the standalone SSE stream, and a second GET is rejected with 409."""
    async with make_client(basic_app) as client:
        # First, we need to initialize a session
        init_response = await client.post(
            "/mcp",
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
        negotiated_version = extract_protocol_version_from_sse(init_response)

        # Now attempt to establish an SSE stream via GET
        get_headers = {
            "Accept": "text/event-stream",
            MCP_SESSION_ID_HEADER: session_id,
            MCP_PROTOCOL_VERSION_HEADER: negotiated_version,
        }
        # The streams enter in order, so the second GET arrives while the first is held open.
        async with (
            client.stream("GET", "/mcp", headers=get_headers) as get_response,
            client.stream("GET", "/mcp", headers=get_headers) as second_get,
        ):
            # Verify we got a successful response with the right content type
            assert get_response.status_code == 200
            assert get_response.headers.get("Content-Type") == "text/event-stream"

            # The second GET gets CONFLICT (409): only one standalone stream is allowed per session.
            assert second_get.status_code == 409


@pytest.mark.anyio
async def test_get_validation(basic_app: Starlette) -> None:
    """A GET without an Accept header covering text/event-stream is rejected with 406."""
    async with make_client(basic_app) as client:
        # First, we need to initialize a session
        init_response = await client.post(
            "/mcp",
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
        negotiated_version = extract_protocol_version_from_sse(init_response)

        # Test without Accept header (suppress the httpx client default Accept: */*)
        del client.headers["accept"]
        response = await client.get(
            "/mcp",
            headers={
                MCP_SESSION_ID_HEADER: session_id,
                MCP_PROTOCOL_VERSION_HEADER: negotiated_version,
            },
        )
        assert response.status_code == 406
        assert "Not Acceptable" in response.text

        # Test with wrong Accept header
        response = await client.get(
            "/mcp",
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
async def initialized_client_session(basic_app: Starlette) -> AsyncIterator[ClientSession]:
    """Create initialized StreamableHTTP client session."""
    async with (
        make_client(basic_app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        yield session


@pytest.mark.anyio
async def test_streamable_http_client_basic_connection(basic_app: Starlette) -> None:
    """A client initializes against a server over the StreamableHTTP transport."""
    async with (
        make_client(basic_app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        result = await session.initialize()
        assert isinstance(result, InitializeResult)
        assert result.server_info.name == SERVER_NAME


@pytest.mark.anyio
async def test_streamable_http_client_resource_read(initialized_client_session: ClientSession) -> None:
    """A resource read round-trips its arguments and the handler's content."""
    response = await initialized_client_session.read_resource(uri="foobar://test-resource")
    assert len(response.contents) == 1
    assert response.contents[0].uri == "foobar://test-resource"
    assert isinstance(response.contents[0], TextResourceContents)
    assert response.contents[0].text == "Read test-resource"


@pytest.mark.anyio
async def test_streamable_http_client_tool_invocation(initialized_client_session: ClientSession) -> None:
    """A tool call reaches the handler and returns its content."""
    # First list tools
    tools = await initialized_client_session.list_tools()
    assert len(tools.tools) == 8
    assert tools.tools[0].name == "test_tool"

    # Call the tool
    result = await initialized_client_session.call_tool("test_tool", {})
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert result.content[0].text == "Called test_tool"


@pytest.mark.anyio
async def test_streamable_http_client_error_handling(initialized_client_session: ClientSession) -> None:
    """A server-side error reaches the client as an MCPError with the handler's message."""
    with pytest.raises(MCPError) as exc_info:
        await initialized_client_session.read_resource(uri="unknown://test-error")
    assert exc_info.value.error.code == 0
    assert "Unknown resource: unknown://test-error" in exc_info.value.error.message


@pytest.mark.anyio
async def test_streamable_http_client_session_persistence(basic_app: Starlette) -> None:
    """The session persists across multiple requests on one connection."""
    async with (
        make_client(basic_app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        # Initialize the session
        result = await session.initialize()
        assert isinstance(result, InitializeResult)

        # Make multiple requests to verify session persistence
        tools = await session.list_tools()
        assert len(tools.tools) == 8

        # Read a resource
        resource = await session.read_resource(uri="foobar://test-persist")
        assert isinstance(resource.contents[0], TextResourceContents) is True
        content = resource.contents[0]
        assert isinstance(content, TextResourceContents)
        assert content.text == "Read test-persist"


@pytest.mark.anyio
async def test_streamable_http_client_json_response(json_app: Starlette) -> None:
    """The client works identically against a server in JSON response mode."""
    async with (
        make_client(json_app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        # Initialize the session
        result = await session.initialize()
        assert isinstance(result, InitializeResult)
        assert result.server_info.name == SERVER_NAME

        # Check tool listing
        tools = await session.list_tools()
        assert len(tools.tools) == 8

        # Call a tool and verify JSON response handling
        result = await session.call_tool("test_tool", {})
        assert len(result.content) == 1
        assert result.content[0].type == "text"
        assert result.content[0].text == "Called test_tool"


@pytest.mark.anyio
async def test_streamable_http_client_get_stream(basic_app: Starlette) -> None:
    """A server-initiated notification reaches the client on the standalone GET stream."""
    notifications_received: list[types.ServerNotification] = []

    # Define message handler to capture notifications
    async def message_handler(  # pragma: no branch
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, types.ServerNotification):  # pragma: no branch
            notifications_received.append(message)

    async with (
        make_client(basic_app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream, message_handler=message_handler) as session,
    ):
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
            if isinstance(notif, types.ResourceUpdatedNotification):  # pragma: no branch
                assert str(notif.params.uri) == "http://test_resource"
                resource_update_found = True

        assert resource_update_found, "ResourceUpdatedNotification not received via GET stream"


def create_session_id_capturing_client(app: Starlette) -> tuple[httpx.AsyncClient, list[str]]:
    """Create an in-process httpx client that captures the session ID from responses."""
    captured_ids: list[str] = []

    async def capture_session_id(response: httpx.Response) -> None:
        session_id = response.headers.get(MCP_SESSION_ID_HEADER)
        if session_id:
            captured_ids.append(session_id)

    client = httpx.AsyncClient(
        transport=StreamingASGITransport(app),
        base_url=BASE_URL,
        follow_redirects=True,
        event_hooks={"response": [capture_session_id]},
    )
    return client, captured_ids


@pytest.mark.anyio
async def test_streamable_http_client_session_termination(basic_app: Starlette) -> None:
    """After the client terminates its session on close, a new connection with that session ID fails."""
    # Use httpx client with event hooks to capture session ID
    httpx_client, captured_ids = create_session_id_capturing_client(basic_app)

    async with httpx_client:
        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=httpx_client) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                # Initialize the session
                result = await session.initialize()
                assert isinstance(result, InitializeResult)
                assert len(captured_ids) > 0
                captured_session_id = captured_ids[0]
                assert captured_session_id is not None
                headers = {MCP_SESSION_ID_HEADER: captured_session_id}

                # Make a request to confirm session is working
                tools = await session.list_tools()
                assert len(tools.tools) == 8

    async with make_client(basic_app, headers=headers) as httpx_client2:
        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=httpx_client2) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                # Attempt to make a request after termination
                with pytest.raises(MCPError, match="Session terminated"):  # pragma: no branch
                    await session.list_tools()


@pytest.mark.anyio
async def test_streamable_http_client_session_termination_204(
    basic_app: Starlette, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Session termination also succeeds when the server answers the DELETE with 204.

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

    # Use httpx client with event hooks to capture session ID
    httpx_client, captured_ids = create_session_id_capturing_client(basic_app)

    async with httpx_client:
        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=httpx_client) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                # Initialize the session
                result = await session.initialize()
                assert isinstance(result, InitializeResult)
                assert len(captured_ids) > 0
                captured_session_id = captured_ids[0]
                assert captured_session_id is not None
                headers = {MCP_SESSION_ID_HEADER: captured_session_id}

                # Make a request to confirm session is working
                tools = await session.list_tools()
                assert len(tools.tools) == 8

    async with make_client(basic_app, headers=headers) as httpx_client2:
        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=httpx_client2) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                # Attempt to make a request after termination
                with pytest.raises(MCPError, match="Session terminated"):  # pragma: no branch
                    await session.list_tools()


@pytest.mark.anyio
async def test_streamable_http_client_resumption(event_app: tuple[SimpleEventStore, Starlette]) -> None:
    """A second client resumes an interrupted request with a resumption token and receives the rest."""
    _, app = event_app

    # Variables to track the state
    captured_resumption_token: str | None = None
    captured_notifications: list[types.ServerNotification] = []
    first_notification_received = anyio.Event()
    resumption_token_received = anyio.Event()

    async def message_handler(  # pragma: no branch
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, types.ServerNotification):  # pragma: no branch
            captured_notifications.append(message)
            # Look for our first notification
            if isinstance(message, types.LoggingMessageNotification):  # pragma: no branch
                if message.params.data == "First notification before lock":
                    first_notification_received.set()

    async def on_resumption_token_update(token: str) -> None:
        nonlocal captured_resumption_token
        captured_resumption_token = token
        resumption_token_received.set()

    # Use httpx client with event hooks to capture session ID
    httpx_client, captured_ids = create_session_id_capturing_client(app)

    # First, start the client session and begin the tool that waits on lock
    async with httpx_client:
        async with streamable_http_client(f"{BASE_URL}/mcp", terminate_on_close=False, http_client=httpx_client) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(  # pragma: no branch
                read_stream, write_stream, message_handler=message_handler
            ) as session:
                # Initialize the session
                result = await session.initialize()
                assert isinstance(result, InitializeResult)
                assert len(captured_ids) > 0
                captured_session_id = captured_ids[0]
                assert captured_session_id is not None
                # Build phase-2 headers now while both values are in scope
                headers: dict[str, Any] = {
                    MCP_SESSION_ID_HEADER: captured_session_id,
                    MCP_PROTOCOL_VERSION_HEADER: result.protocol_version,
                }

                # Start the tool that will wait on lock in a task
                async with anyio.create_task_group() as tg:  # pragma: no branch

                    async def run_tool():
                        metadata = ClientMessageMetadata(
                            on_resumption_token_update=on_resumption_token_update,
                        )
                        await session.send_request(
                            types.CallToolRequest(
                                params=types.CallToolRequestParams(
                                    name="wait_for_lock_with_notification", arguments={}
                                ),
                            ),
                            types.CallToolResult,
                            metadata=metadata,
                        )

                    tg.start_soon(run_tool)

                    # Wait for the first notification and resumption token
                    with anyio.fail_after(5):
                        await first_notification_received.wait()
                        await resumption_token_received.wait()

                    # first_notification_received is set by message_handler immediately
                    # after appending to captured_notifications. The server tool is
                    # blocked on its lock, so nothing else can arrive before we cancel.
                    assert len(captured_notifications) == 1
                    assert isinstance(captured_notifications[0], types.LoggingMessageNotification)
                    assert captured_notifications[0].params.data == "First notification before lock"
                    # Reset for phase 2 before cancelling
                    captured_notifications.clear()

                    # Kill the client session while tool is waiting on lock
                    tg.cancel_scope.cancel()

    async with make_client(app, headers=headers) as httpx_client2:
        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=httpx_client2) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(
                read_stream, write_stream, message_handler=message_handler
            ) as session:  # pragma: no branch
                result = await session.send_request(
                    types.CallToolRequest(params=types.CallToolRequestParams(name="release_lock", arguments={})),
                    types.CallToolResult,
                )
                metadata = ClientMessageMetadata(
                    resumption_token=captured_resumption_token,
                )

                result = await session.send_request(
                    types.CallToolRequest(
                        params=types.CallToolRequestParams(name="wait_for_lock_with_notification", arguments={}),
                    ),
                    types.CallToolResult,
                    metadata=metadata,
                )
                assert len(result.content) == 1
                assert result.content[0].type == "text"
                assert result.content[0].text == "Completed"

                # We should have received the remaining notifications
                assert len(captured_notifications) == 1
                assert isinstance(captured_notifications[0], types.LoggingMessageNotification)
                assert captured_notifications[0].params.data == "Second notification after lock"


@pytest.mark.anyio
async def test_streamablehttp_server_sampling(basic_app: Starlette) -> None:
    """A server-initiated sampling request reaches the client callback and its result the tool."""
    # Variable to track if sampling callback was invoked
    sampling_callback_invoked = False
    captured_message_params = None

    # Define sampling callback that returns a mock response
    async def sampling_callback(
        context: RequestContext[ClientSession],
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
            stop_reason="endTurn",
        )

    # Create client with sampling callback
    async with (
        make_client(basic_app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream, sampling_callback=sampling_callback) as session,
    ):
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
async def _handle_context_list_tools(
    ctx: ServerRequestContext, params: PaginatedRequestParams | None
) -> ListToolsResult:
    return ListToolsResult(
        tools=[
            Tool(
                name="echo_headers",
                description="Echo request headers from context",
                input_schema={"type": "object", "properties": {}},
            ),
            Tool(
                name="echo_context",
                description="Echo request context with custom data",
                input_schema={
                    "type": "object",
                    "properties": {
                        "request_id": {"type": "string"},
                    },
                    "required": ["request_id"],
                },
            ),
        ]
    )


async def _handle_context_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    assert params.name in ("echo_headers", "echo_context")
    assert isinstance(ctx.request, Request)

    if params.name == "echo_headers":
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(dict(ctx.request.headers)))])

    assert params.arguments is not None
    context_data: dict[str, Any] = {
        "request_id": params.arguments.get("request_id"),
        "headers": dict(ctx.request.headers),
        "method": ctx.request.method,
        "path": ctx.request.url.path,
    }
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(context_data))])


@pytest.fixture
async def context_app() -> AsyncIterator[Starlette]:
    """An app whose server echoes request context, served in process."""
    server = Server(
        "ContextAwareServer",
        on_list_tools=_handle_context_list_tools,
        on_call_tool=_handle_context_call_tool,
    )
    session_manager = StreamableHTTPSessionManager(
        app=server,
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    app = Starlette(routes=[Mount("/mcp", app=session_manager.handle_request)])
    async with session_manager.run():
        yield app


@pytest.mark.anyio
async def test_streamablehttp_request_context_propagation(context_app: Starlette) -> None:
    """Custom HTTP headers on the connection are visible to server handlers via ctx.request."""
    custom_headers = {
        "Authorization": "Bearer test-token",
        "X-Custom-Header": "test-value",
        "X-Trace-Id": "trace-123",
    }

    async with make_client(context_app, headers=custom_headers) as httpx_client:
        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=httpx_client) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                result = await session.initialize()
                assert isinstance(result, InitializeResult)
                assert result.server_info.name == "ContextAwareServer"

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
async def test_streamablehttp_request_context_isolation(context_app: Starlette) -> None:
    """Each connection's handlers see only that connection's request headers."""
    contexts: list[dict[str, Any]] = []

    # Connect three clients in turn, each with its own headers.
    for i in range(3):
        headers = {
            "X-Request-Id": f"request-{i}",
            "X-Custom-Value": f"value-{i}",
            "Authorization": f"Bearer token-{i}",
        }

        async with make_client(context_app, headers=headers) as httpx_client:
            async with streamable_http_client(f"{BASE_URL}/mcp", http_client=httpx_client) as (
                read_stream,
                write_stream,
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
    assert len(contexts) == 3
    for i, ctx in enumerate(contexts):
        assert ctx["request_id"] == f"request-{i}"
        assert ctx["headers"].get("x-request-id") == f"request-{i}"
        assert ctx["headers"].get("x-custom-value") == f"value-{i}"
        assert ctx["headers"].get("authorization") == f"Bearer token-{i}"


@pytest.mark.anyio
async def test_client_includes_protocol_version_header_after_init(context_app: Starlette) -> None:
    """After initialization, every client request carries the negotiated protocol version header."""
    async with (
        make_client(context_app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        # Initialize and get the negotiated version
        init_result = await session.initialize()
        negotiated_version = init_result.protocol_version

        # Call a tool that echoes headers to verify the header is present
        tool_result = await session.call_tool("echo_headers", {})

        assert len(tool_result.content) == 1
        assert isinstance(tool_result.content[0], TextContent)
        headers_data = json.loads(tool_result.content[0].text)

        # Verify protocol version header is present
        assert "mcp-protocol-version" in headers_data
        assert headers_data[MCP_PROTOCOL_VERSION_HEADER] == negotiated_version


@pytest.mark.anyio
async def test_server_validates_protocol_version_header(basic_app: Starlette) -> None:
    """An invalid or unsupported protocol version header is rejected with 400; the negotiated one passes."""
    async with make_client(basic_app) as client:
        # First initialize a session to get a valid session ID
        init_response = await client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json=INIT_REQUEST,
        )
        assert init_response.status_code == 200
        session_id = init_response.headers.get(MCP_SESSION_ID_HEADER)
        assert session_id is not None

        # Test request with invalid protocol version (should fail)
        response = await client.post(
            "/mcp",
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
        response = await client.post(
            "/mcp",
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

        response = await client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                MCP_SESSION_ID_HEADER: session_id,
                MCP_PROTOCOL_VERSION_HEADER: negotiated_version,
            },
            json={"jsonrpc": "2.0", "method": "tools/list", "id": "test-4"},
        )
        assert response.status_code == 200


@pytest.mark.anyio
async def test_server_backwards_compatibility_no_protocol_version(basic_app: Starlette) -> None:
    """A request without a protocol version header is accepted for backwards compatibility."""
    async with make_client(basic_app) as client:
        # First initialize a session to get a valid session ID
        init_response = await client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json=INIT_REQUEST,
        )
        assert init_response.status_code == 200
        session_id = init_response.headers.get(MCP_SESSION_ID_HEADER)
        assert session_id is not None

        # Test request without mcp-protocol-version header (backwards compatibility)
        async with client.stream(
            "POST",
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                MCP_SESSION_ID_HEADER: session_id,
            },
            json={"jsonrpc": "2.0", "method": "tools/list", "id": "test-backwards-compat"},
        ) as response:
            assert response.status_code == 200  # Should succeed for backwards compatibility
            assert response.headers.get("Content-Type") == "text/event-stream"


@pytest.mark.anyio
async def test_client_crash_handled(basic_app: Starlette) -> None:
    """A client crashing mid-session does not prevent later clients from connecting."""

    # Simulate bad client that crashes after init
    async def bad_client():
        """Client that triggers ClosedResourceError"""
        async with (
            make_client(basic_app) as http_client,
            streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            raise Exception("client crash")

    # Run bad client a few times to trigger the crash. The crash surfaces wrapped in exception
    # groups whose exact shape is not the subject here — what matters is that the server survives.
    for _ in range(3):
        try:
            await bad_client()
        except Exception:
            pass

    # Try a good client, it should still be able to connect and list tools
    async with (
        make_client(basic_app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        result = await session.initialize()
        assert isinstance(result, InitializeResult)
        tools = await session.list_tools()
        assert tools.tools


@pytest.mark.anyio
async def test_handle_sse_event_skips_empty_data() -> None:
    """_handle_sse_event skips empty SSE data (keep-alive pings) without writing to the stream."""
    transport = StreamableHTTPTransport(url="http://localhost:8000/mcp")

    # Create a mock SSE event with empty data (keep-alive ping)
    mock_sse = ServerSentEvent(event="message", data="", id=None, retry=None)

    # Create a context-aware stream writer (matches StreamWriter type alias)
    write_stream, read_stream = create_context_streams[SessionMessage | Exception](1)

    try:
        # Call _handle_sse_event with empty data - should return False and not raise
        result = await transport._handle_sse_event(mock_sse, write_stream)

        # Should return False (not complete) for empty data
        assert result is False

        # Nothing should have been written to the stream
        with pytest.raises(TimeoutError):
            with anyio.fail_after(0):
                await read_stream.receive()
    finally:
        await write_stream.aclose()
        await read_stream.aclose()


@pytest.mark.anyio
async def test_priming_event_not_sent_for_old_protocol_version() -> None:
    """_maybe_send_priming_event skips for old protocol versions (backwards compat)."""
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
async def test_priming_event_not_sent_without_event_store() -> None:
    """_maybe_send_priming_event returns early when no event_store is configured."""
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
async def test_priming_event_includes_retry_interval() -> None:
    """_maybe_send_priming_event includes the retry field when retry_interval is set."""
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
async def test_close_sse_stream_callback_not_provided_for_old_protocol_version() -> None:
    """close_sse_stream callbacks are only provided for protocol versions that support polling."""
    # Create a transport with an event store
    transport = StreamableHTTPServerTransport(
        "/mcp",
        event_store=SimpleEventStore(),
    )

    # Create a mock message and request
    mock_message = JSONRPCRequest(jsonrpc="2.0", id="test-1", method="tools/list")
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
    event_app: tuple[SimpleEventStore, Starlette],
) -> None:
    """Client should receive priming event (resumption token update) on POST SSE stream."""
    _, app = event_app

    captured_resumption_tokens: list[str] = []

    async def on_resumption_token_update(token: str) -> None:
        captured_resumption_tokens.append(token)

    async with (
        make_client(app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # Call tool with resumption token callback via send_request
        metadata = ClientMessageMetadata(
            on_resumption_token_update=on_resumption_token_update,
        )
        result = await session.send_request(
            types.CallToolRequest(params=types.CallToolRequestParams(name="test_tool", arguments={})),
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
    event_app: tuple[SimpleEventStore, Starlette],
) -> None:
    """Server tool can call ctx.close_sse_stream() to close connection."""
    _, app = event_app

    async with (
        make_client(app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # Call tool that closes stream mid-operation
        result = await session.call_tool("tool_with_stream_close", {})

        # Client should still receive complete response (via auto-reconnect)
        assert result is not None
        assert len(result.content) > 0
        assert result.content[0].type == "text"
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Done"


@pytest.mark.anyio
async def test_streamable_http_client_auto_reconnects(
    event_app: tuple[SimpleEventStore, Starlette],
) -> None:
    """Client should auto-reconnect with Last-Event-ID when server closes after priming event."""
    _, app = event_app
    captured_notifications: list[str] = []

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):  # pragma: no branch
            return  # pragma: no cover
        if isinstance(message, types.ServerNotification):  # pragma: no branch
            if isinstance(message, types.LoggingMessageNotification):  # pragma: no branch
                captured_notifications.append(str(message.params.data))

    async with (
        make_client(app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream, message_handler=message_handler) as session,
    ):
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
    event_app: tuple[SimpleEventStore, Starlette],
) -> None:
    """Client MUST respect retry field, waiting specified ms before reconnecting."""
    _, app = event_app

    async with (
        make_client(app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        start_time = time.monotonic()
        result = await session.call_tool("tool_with_stream_close", {})
        elapsed = time.monotonic() - start_time

        # Verify result was received
        assert result.content[0].type == "text"
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Done"

        # The elapsed time should include at least the retry interval (500ms) before
        # the client reconnected; the tool's own work only accounts for ~100ms.
        assert elapsed >= 0.4, f"Client should wait ~500ms before reconnecting, but elapsed time was {elapsed:.3f}s"


@pytest.mark.anyio
async def test_streamable_http_sse_polling_full_cycle(
    event_app: tuple[SimpleEventStore, Starlette],
) -> None:
    """End-to-end test: server closes stream, client reconnects, receives all events."""
    _, app = event_app
    all_notifications: list[str] = []

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):  # pragma: no branch
            return  # pragma: no cover
        if isinstance(message, types.ServerNotification):  # pragma: no branch
            if isinstance(message, types.LoggingMessageNotification):  # pragma: no branch
                all_notifications.append(str(message.params.data))

    async with (
        make_client(app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream, message_handler=message_handler) as session,
    ):
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
    event_app: tuple[SimpleEventStore, Starlette],
) -> None:
    """Events sent while client is disconnected should be replayed on reconnect."""
    _, app = event_app
    notification_data: list[str] = []

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):  # pragma: no branch
            return  # pragma: no cover
        if isinstance(message, types.ServerNotification):  # pragma: no branch
            if isinstance(message, types.LoggingMessageNotification):  # pragma: no branch
                notification_data.append(str(message.params.data))

    async with (
        make_client(app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream, message_handler=message_handler) as session,
    ):
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
async def test_streamable_http_multiple_reconnections() -> None:
    """Every close_sse_stream() severs a live connection and triggers its own client reconnect.

    The tool closes its SSE stream three times; before each next cycle it waits until the
    client has observed the previous cycle's two new resumption tokens (the checkpoint and the
    new connection's priming event). The priming event is sent only after the server has
    re-registered the resumed stream, so once the client holds its token the next close is
    guaranteed to sever a live connection rather than silently no-op — making the exact token
    count below a consequence of causality, not timing margins. This pins reconnect-per-close
    accounting; reconnect *latency* is pinned by test_streamable_http_client_respects_retry_interval.

    With 3 checkpoints, we expect 8 resumption tokens:
    - 1 priming (initial POST connection)
    - 3 notifications (checkpoint_0, checkpoint_1, checkpoint_2)
    - 3 priming (one per reconnect after each close)
    - 1 response
    """
    resumption_tokens: list[str] = []
    # milestones[n] fires when the client has observed n tokens. After the initial priming
    # (token 1), each completed cycle i contributes exactly two tokens — checkpoint_i and the
    # reconnect's priming, in either order — so cycle i is complete at 3 + 2i tokens.
    milestones = {3: anyio.Event(), 5: anyio.Event(), 7: anyio.Event()}

    async def on_resumption_token(token: str) -> None:
        resumption_tokens.append(token)
        milestone = milestones.get(len(resumption_tokens))
        if milestone is not None:
            milestone.set()

    async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "multi_close_tool"
        for i, milestone in enumerate(milestones.values()):
            await ctx.session.send_log_message(
                level="info",
                data=f"checkpoint_{i}",
                logger="multi_close_tool",
                related_request_id=ctx.request_id,
            )
            assert ctx.close_sse_stream is not None
            await ctx.close_sse_stream()
            # Client and server share one event loop, so the tool can wait directly on the
            # client-side callback observing the reconnect.
            with anyio.fail_after(5):
                await milestone.wait()
        return CallToolResult(content=[TextContent(type="text", text="Completed 3 checkpoints")])

    server = Server("multi_reconnect_server", on_call_tool=handle_call_tool)

    async with (
        # retry_interval is small to keep the test fast, but nonzero so each dying connection
        # finishes unwinding before its replacement registers.
        running_app(event_store=SimpleEventStore(), retry_interval=50, server=server) as app,
        make_client(app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        # Use send_request with metadata to track resumption tokens
        metadata = ClientMessageMetadata(on_resumption_token_update=on_resumption_token)
        result = await session.send_request(
            types.CallToolRequest(
                method="tools/call",
                params=types.CallToolRequestParams(name="multi_close_tool", arguments={}),
            ),
            types.CallToolResult,
            metadata=metadata,
        )

        assert result.content[0].type == "text"
        assert isinstance(result.content[0], TextContent)
        assert "Completed 3 checkpoints" in result.content[0].text

        # 4 priming + 3 notifications + 1 response = 8 tokens. All tokens are
        # captured before send_request returns, so this is safe to check here.
        assert len(resumption_tokens) == 8, (
            f"Expected 8 resumption tokens (4 priming + 3 notifs + 1 response), "
            f"got {len(resumption_tokens)}: {resumption_tokens}"
        )


@pytest.mark.anyio
async def test_standalone_get_stream_reconnection(event_app: tuple[SimpleEventStore, Starlette]) -> None:
    """Test that standalone GET stream automatically reconnects after server closes it.

    Verifies:
    1. Client receives notification 1 via GET stream
    2. Server closes GET stream
    3. Client reconnects with Last-Event-ID
    4. Client receives notification 2 on new connection

    Note: Requires the event store app because close_standalone_sse_stream
    callback is only provided when event_store is configured and protocol version >= 2025-11-25.
    """
    _, app = event_app
    received_notifications: list[str] = []

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):
            return  # pragma: no cover
        if isinstance(message, types.ServerNotification):  # pragma: no branch
            if isinstance(message, types.ResourceUpdatedNotification):  # pragma: no branch
                received_notifications.append(str(message.params.uri))

    async with (
        make_client(app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream, message_handler=message_handler) as session,
    ):
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
        assert "http://notification_1" in received_notifications, (
            f"Should receive notification 1 (sent before GET stream close), got: {received_notifications}"
        )
        assert "http://notification_2" in received_notifications, (
            f"Should receive notification 2 after reconnect, got: {received_notifications}"
        )


@pytest.mark.anyio
async def test_streamable_http_client_does_not_mutate_provided_client(basic_app: Starlette) -> None:
    """streamable_http_client does not mutate the provided httpx client's headers."""
    # Create a client with custom headers
    original_headers = {
        "X-Custom-Header": "custom-value",
        "Authorization": "Bearer test-token",
    }

    async with make_client(basic_app, headers=original_headers) as custom_client:
        # Use the client with streamable_http_client
        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=custom_client) as (
            read_stream,
            write_stream,
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
async def test_streamable_http_client_mcp_headers_override_defaults(context_app: Starlette) -> None:
    """MCP protocol headers override the httpx client's default headers in actual requests."""
    # httpx.AsyncClient has default "accept: */*" header
    # We need to verify that our MCP accept header overrides it in actual requests

    async with make_client(context_app) as client:
        # Verify client has default accept header
        assert client.headers.get("accept") == "*/*"

        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=client) as (read_stream, write_stream):
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
async def test_streamable_http_client_preserves_custom_with_mcp_headers(context_app: Starlette) -> None:
    """Custom client headers and MCP protocol headers are both sent in requests."""
    custom_headers = {
        "X-Custom-Header": "custom-value",
        "X-Request-Id": "req-123",
        "Authorization": "Bearer test-token",
    }

    async with make_client(context_app, headers=custom_headers) as client:
        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=client) as (read_stream, write_stream):
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
