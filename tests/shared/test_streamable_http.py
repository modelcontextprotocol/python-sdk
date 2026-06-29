"""Tests for the StreamableHTTP server and client transport, driven entirely in process."""

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
import mcp_types as types
import pytest
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from httpx_sse import ServerSentEvent
from mcp_types import (
    DEFAULT_NEGOTIATED_VERSION,
    INVALID_PARAMS,
    INVALID_REQUEST,
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
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount
from starlette.types import Message, Scope

from mcp import MCPError
from mcp.client import ClientRequestContext
from mcp.client.session import ClientSession
from mcp.client.streamable_http import StreamableHTTPTransport, streamable_http_client
from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http import (
    GET_STREAM_KEY,
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
from mcp.shared._compat import resync_tracer
from mcp.shared._context_streams import create_context_streams
from mcp.shared.message import ClientMessageMetadata, ServerMessageMetadata, SessionMessage
from mcp.shared.session import RequestResponder
from tests.interaction.transports import StreamingASGITransport

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


def first_sse_data(response: httpx.Response) -> dict[str, Any]:
    """Return the first SSE `data:` payload of a response, parsed as JSON."""
    assert response.headers.get("Content-Type") == "text/event-stream"
    for line in response.text.splitlines():
        if line.startswith("data: "):
            return json.loads(line.removeprefix("data: "))
    raise ValueError("No data event in SSE response")  # pragma: no cover


def extract_protocol_version_from_sse(response: httpx.Response) -> str:
    return first_sse_data(response)["result"]["protocolVersion"]


class SimpleEventStore(EventStore):
    """Simple in-memory event store for testing."""

    def __init__(self):
        self._events: list[tuple[StreamId, EventId, types.JSONRPCMessage | None]] = []
        self._event_id_counter = 0

    async def store_event(self, stream_id: StreamId, message: types.JSONRPCMessage | None) -> EventId:
        self._event_id_counter += 1
        event_id = str(self._event_id_counter)
        self._events.append((stream_id, event_id, message))
        return event_id

    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: EventCallback,
    ) -> StreamId | None:
        # Find the stream ID of the last event; clients always resume from a stored event.
        target_stream_id = next(stream_id for stream_id, event_id, _ in self._events if event_id == last_event_id)

        last_event_id_int = int(last_event_id)

        # Replay later events from the same stream, skipping priming events (None message).
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

    if name == "test_tool_with_standalone_notification":
        await ctx.session.send_resource_updated(uri="http://test_resource")
        return CallToolResult(content=[TextContent(type="text", text=f"Called {name}")])

    elif name == "test_sampling_tool":
        sampling_result = await ctx.session.create_message(  # pyright: ignore[reportDeprecated]
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
        await ctx.session.send_log_message(  # pyright: ignore[reportDeprecated]
            level="info",
            data="First notification before lock",
            logger="lock_tool",
            related_request_id=ctx.request_id,
        )

        await ctx.lifespan_context.lock.wait()

        await ctx.session.send_log_message(  # pyright: ignore[reportDeprecated]
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
        await ctx.session.send_log_message(  # pyright: ignore[reportDeprecated]
            level="info",
            data="Before close",
            logger="stream_close_tool",
            related_request_id=ctx.request_id,
        )
        assert ctx.close_sse_stream is not None
        await ctx.close_sse_stream()
        await anyio.sleep(0.1)
        await ctx.session.send_log_message(  # pyright: ignore[reportDeprecated]
            level="info",
            data="After close",
            logger="stream_close_tool",
            related_request_id=ctx.request_id,
        )
        return CallToolResult(content=[TextContent(type="text", text="Done")])

    elif name == "tool_with_multiple_notifications_and_close":
        await ctx.session.send_log_message(  # pyright: ignore[reportDeprecated]
            level="info",
            data="notification1",
            logger="multi_notif_tool",
            related_request_id=ctx.request_id,
        )
        assert ctx.close_sse_stream is not None
        await ctx.close_sse_stream()
        await anyio.sleep(0.1)
        await ctx.session.send_log_message(  # pyright: ignore[reportDeprecated]
            level="info",
            data="notification2",
            logger="multi_notif_tool",
            related_request_id=ctx.request_id,
        )
        await ctx.session.send_log_message(  # pyright: ignore[reportDeprecated]
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

    `retry_interval` is in milliseconds; `server` defaults to the file's shared test server.
    """
    # DNS rebinding cannot affect an in-process app; the protection itself is pinned by
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
    """An in-process httpx client for `app`, following redirects like `create_mcp_http_client`
    (Starlette's Mount 307-redirects the bare /mcp path to /mcp/)."""
    return httpx.AsyncClient(
        transport=StreamingASGITransport(app), base_url=BASE_URL, headers=headers, follow_redirects=True
    )


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
    return SimpleEventStore()


@pytest.fixture
async def event_app(event_store: SimpleEventStore) -> AsyncIterator[tuple[SimpleEventStore, Starlette]]:
    async with running_app(event_store=event_store, retry_interval=500) as app:
        yield event_store, app


@pytest.mark.anyio
async def test_accept_header_validation(basic_app: Starlette) -> None:
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
    valid_session_ids = [
        "test-session-id",
        "1234567890",
        "session!@#$%^&*()_+-=[]{}|;:,.<>?/",
        "~`",
    ]

    for session_id in valid_session_ids:
        assert SESSION_ID_PATTERN.match(session_id) is not None
        assert SESSION_ID_PATTERN.fullmatch(session_id) is not None

    invalid_session_ids = [
        "",
        " test",  # leading space (0x20)
        "test\t",
        "test\n",
        "test\r",
        "test" + chr(0x7F),  # DEL
        "test" + chr(0x80),  # extended ASCII
        "test" + chr(0x00),
        "test" + chr(0x20),  # trailing space
    ]

    for session_id in invalid_session_ids:
        # match() may succeed on a partial match; fullmatch must always fail.
        if SESSION_ID_PATTERN.match(session_id) is not None:
            assert SESSION_ID_PATTERN.fullmatch(session_id) is None


def test_streamable_http_transport_init_validation() -> None:
    """StreamableHTTPServerTransport accepts valid or absent session IDs and rejects invalid ones."""
    valid_transport = StreamableHTTPServerTransport(mcp_session_id="valid-id")
    assert valid_transport.mcp_session_id == "valid-id"

    none_transport = StreamableHTTPServerTransport(mcp_session_id=None)
    assert none_transport.mcp_session_id is None

    with pytest.raises(ValueError) as excinfo:
        StreamableHTTPServerTransport(mcp_session_id="invalid id with space")
    assert "Session ID must only contain visible ASCII characters" in str(excinfo.value)

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

        negotiated_version = extract_protocol_version_from_sse(response)

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

        negotiated_version = extract_protocol_version_from_sse(response)

        session_id = response.headers.get(MCP_SESSION_ID_HEADER)
        assert session_id is not None

        async with client.stream(
            "POST",
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                MCP_SESSION_ID_HEADER: session_id,
                MCP_PROTOCOL_VERSION_HEADER: negotiated_version,
            },
            json={"jsonrpc": "2.0", "method": "tools/list", "id": "tools-1"},
        ) as tools_response:
            assert tools_response.status_code == 200
            assert tools_response.headers.get("Content-Type") == "text/event-stream"


@pytest.mark.anyio
async def test_json_response(json_app: Starlette) -> None:
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
    async with make_client(json_app) as client:
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
        negotiated_version = extract_protocol_version_from_sse(init_response)

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
            assert get_response.status_code == 200
            assert get_response.headers.get("Content-Type") == "text/event-stream"

            # Only one standalone stream is allowed per session.
            assert second_get.status_code == 409


@pytest.mark.anyio
async def test_get_validation(basic_app: Starlette) -> None:
    """A GET without an Accept header covering text/event-stream is rejected with 406."""
    async with make_client(basic_app) as client:
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
        negotiated_version = extract_protocol_version_from_sse(init_response)

        # Suppress the httpx client default Accept: */* header
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


@pytest.fixture
async def initialized_client_session(basic_app: Starlette) -> AsyncIterator[ClientSession]:
    async with (
        make_client(basic_app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        yield session


@pytest.mark.anyio
async def test_streamable_http_client_basic_connection(basic_app: Starlette) -> None:
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
    response = await initialized_client_session.read_resource(uri="foobar://test-resource")
    assert len(response.contents) == 1
    assert response.contents[0].uri == "foobar://test-resource"
    assert isinstance(response.contents[0], TextResourceContents)
    assert response.contents[0].text == "Read test-resource"


@pytest.mark.anyio
async def test_streamable_http_client_tool_invocation(initialized_client_session: ClientSession) -> None:
    tools = await initialized_client_session.list_tools()
    assert len(tools.tools) == 8
    assert tools.tools[0].name == "test_tool"

    result = await initialized_client_session.call_tool("test_tool", {})
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert result.content[0].text == "Called test_tool"


@pytest.mark.anyio
async def test_streamable_http_client_error_handling(initialized_client_session: ClientSession) -> None:
    with pytest.raises(MCPError) as exc_info:
        await initialized_client_session.read_resource(uri="unknown://test-error")
    assert exc_info.value.error.code == 0
    assert "Unknown resource: unknown://test-error" in exc_info.value.error.message


@pytest.mark.anyio
async def test_streamable_http_client_session_persistence(basic_app: Starlette) -> None:
    async with (
        make_client(basic_app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        result = await session.initialize()
        assert isinstance(result, InitializeResult)

        tools = await session.list_tools()
        assert len(tools.tools) == 8

        resource = await session.read_resource(uri="foobar://test-persist")
        assert isinstance(resource.contents[0], TextResourceContents) is True
        content = resource.contents[0]
        assert isinstance(content, TextResourceContents)
        assert content.text == "Read test-persist"


@pytest.mark.anyio
async def test_streamable_http_client_json_response(json_app: Starlette) -> None:
    async with (
        make_client(json_app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        result = await session.initialize()
        assert isinstance(result, InitializeResult)
        assert result.server_info.name == SERVER_NAME

        tools = await session.list_tools()
        assert len(tools.tools) == 8

        result = await session.call_tool("test_tool", {})
        assert len(result.content) == 1
        assert result.content[0].type == "text"
        assert result.content[0].text == "Called test_tool"


@pytest.mark.anyio
async def test_streamable_http_client_get_stream(basic_app: Starlette) -> None:
    notifications_received: list[types.ServerNotification] = []

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
        # Initialization triggers the standalone GET stream setup.
        result = await session.initialize()
        assert isinstance(result, InitializeResult)

        await session.call_tool("test_tool_with_standalone_notification", {})

        assert len(notifications_received) > 0

        resource_update_found = False
        for notif in notifications_received:
            if isinstance(notif, types.ResourceUpdatedNotification):  # pragma: no branch
                assert str(notif.params.uri) == "http://test_resource"
                resource_update_found = True

        assert resource_update_found, "ResourceUpdatedNotification not received via GET stream"


def create_session_id_capturing_client(app: Starlette) -> tuple[httpx.AsyncClient, list[str]]:
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
    httpx_client, captured_ids = create_session_id_capturing_client(basic_app)

    async with httpx_client:
        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=httpx_client) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                result = await session.initialize()
                assert isinstance(result, InitializeResult)
                assert len(captured_ids) > 0
                captured_session_id = captured_ids[0]
                assert captured_session_id is not None
                headers = {MCP_SESSION_ID_HEADER: captured_session_id}

                tools = await session.list_tools()
                assert len(tools.tools) == 8

    async with make_client(basic_app, headers=headers) as httpx_client2:
        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=httpx_client2) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                with pytest.raises(MCPError) as exc_info:  # pragma: no branch
                    await session.list_tools()
                assert exc_info.value.error.code == INVALID_REQUEST
                assert "terminated" in exc_info.value.error.message.lower()


@pytest.mark.anyio
async def test_streamable_http_client_session_termination_204(
    basic_app: Starlette, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Session termination also succeeds when the server answers the DELETE with 204."""
    original_delete = httpx.AsyncClient.delete

    async def mock_delete(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> httpx.Response:
        response = await original_delete(self, *args, **kwargs)

        mocked_response = httpx.Response(
            204,
            headers=response.headers,
            content=response.content,
            request=response.request,
        )
        return mocked_response

    monkeypatch.setattr(httpx.AsyncClient, "delete", mock_delete)

    httpx_client, captured_ids = create_session_id_capturing_client(basic_app)

    async with httpx_client:
        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=httpx_client) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                result = await session.initialize()
                assert isinstance(result, InitializeResult)
                assert len(captured_ids) > 0
                captured_session_id = captured_ids[0]
                assert captured_session_id is not None
                headers = {MCP_SESSION_ID_HEADER: captured_session_id}

                tools = await session.list_tools()
                assert len(tools.tools) == 8

    async with make_client(basic_app, headers=headers) as httpx_client2:
        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=httpx_client2) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                with pytest.raises(MCPError) as exc_info:  # pragma: no branch
                    await session.list_tools()
                assert exc_info.value.error.code == INVALID_REQUEST
                assert "terminated" in exc_info.value.error.message.lower()


@pytest.mark.anyio
async def test_streamable_http_client_resumption(event_app: tuple[SimpleEventStore, Starlette]) -> None:
    """A second client resumes an interrupted request with a resumption token and receives the rest."""
    _, app = event_app

    captured_resumption_token: str | None = None
    captured_notifications: list[types.ServerNotification] = []
    first_notification_received = anyio.Event()
    resumption_token_received = anyio.Event()

    async def message_handler(  # pragma: no branch
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, types.ServerNotification):  # pragma: no branch
            captured_notifications.append(message)
            if isinstance(message, types.LoggingMessageNotification):  # pragma: no branch
                if message.params.data == "First notification before lock":
                    first_notification_received.set()

    async def on_resumption_token_update(token: str) -> None:
        nonlocal captured_resumption_token
        captured_resumption_token = token
        resumption_token_received.set()

    httpx_client, captured_ids = create_session_id_capturing_client(app)

    async with httpx_client:
        async with streamable_http_client(f"{BASE_URL}/mcp", terminate_on_close=False, http_client=httpx_client) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(  # pragma: no branch
                read_stream, write_stream, message_handler=message_handler
            ) as session:
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

                    with anyio.fail_after(5):
                        await first_notification_received.wait()
                        await resumption_token_received.wait()

                    # message_handler appends before setting the event, and the server tool is
                    # blocked on its lock, so exactly one notification can have arrived.
                    assert len(captured_notifications) == 1
                    assert isinstance(captured_notifications[0], types.LoggingMessageNotification)
                    assert captured_notifications[0].params.data == "First notification before lock"
                    # Reset for phase 2 before cancelling
                    captured_notifications.clear()

                    # Kill the client session while tool is waiting on lock
                    tg.cancel_scope.cancel()

    await resync_tracer()

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

                assert len(captured_notifications) == 1
                assert isinstance(captured_notifications[0], types.LoggingMessageNotification)
                assert captured_notifications[0].params.data == "Second notification after lock"


@pytest.mark.anyio
async def test_streamablehttp_server_sampling(basic_app: Starlette) -> None:
    """A server-initiated sampling request reaches the client callback and its result the tool."""
    sampling_callback_invoked = False
    captured_message_params = None

    async def sampling_callback(
        context: ClientRequestContext,
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

    async with (
        make_client(basic_app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream, sampling_callback=sampling_callback) as session,
    ):
        result = await session.initialize()
        assert isinstance(result, InitializeResult)

        tool_result = await session.call_tool("test_sampling_tool", {})

        assert len(tool_result.content) == 1
        assert tool_result.content[0].type == "text"
        assert "Response from sampling: Received message from server" in tool_result.content[0].text

        assert sampling_callback_invoked
        assert captured_message_params is not None
        assert len(captured_message_params.messages) == 1
        assert captured_message_params.messages[0].content.text == "Server needs client sampling"


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
        "protocol_version": ctx.protocol_version,
        "session_protocol_version": ctx.session.protocol_version,
    }
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(context_data))])


@asynccontextmanager
async def _run_context_app(*, stateless: bool) -> AsyncIterator[Starlette]:
    server = Server(
        "ContextAwareServer",
        on_list_tools=_handle_context_list_tools,
        on_call_tool=_handle_context_call_tool,
    )
    session_manager = StreamableHTTPSessionManager(
        app=server,
        stateless=stateless,
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    app = Starlette(routes=[Mount("/mcp", app=session_manager.handle_request)])
    async with session_manager.run():
        yield app


@pytest.fixture
async def context_app() -> AsyncIterator[Starlette]:
    async with _run_context_app(stateless=False) as app:
        yield app


@pytest.fixture
async def stateless_context_app() -> AsyncIterator[Starlette]:
    async with _run_context_app(stateless=True) as app:
        yield app


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("header_value", "expected"),
    [
        ("2025-06-18", "2025-06-18"),
        ("2025-11-25", "2025-11-25"),
        (None, DEFAULT_NEGOTIATED_VERSION),
    ],
)
async def test_streamablehttp_stateless_ctx_protocol_version_tracks_the_header(
    stateless_context_app: Starlette, header_value: str | None, expected: str
) -> None:
    """No handshake on stateless: the header (or the spec's 2025-03-26 default) reaches `ctx.protocol_version`."""
    body = JSONRPCRequest(
        jsonrpc="2.0",
        id=1,
        method="tools/call",
        params={"name": "echo_context", "arguments": {"request_id": "r"}},
    )
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    if header_value is not None:
        headers[MCP_PROTOCOL_VERSION_HEADER] = header_value
    async with make_client(stateless_context_app) as client:
        response = await client.post(
            f"{BASE_URL}/mcp", json=body.model_dump(by_alias=True, exclude_none=True), headers=headers
        )
    assert response.status_code == 200
    echoed = json.loads(first_sse_data(response)["result"]["content"][0]["text"])
    assert echoed["protocol_version"] == expected
    assert echoed["session_protocol_version"] == expected


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

                tool_result = await session.call_tool("echo_headers", {})

                assert len(tool_result.content) == 1
                assert isinstance(tool_result.content[0], TextContent)
                headers_data = json.loads(tool_result.content[0].text)

                assert headers_data.get("authorization") == "Bearer test-token"
                assert headers_data.get("x-custom-header") == "test-value"
                assert headers_data.get("x-trace-id") == "trace-123"


@pytest.mark.anyio
async def test_streamablehttp_request_context_isolation(context_app: Starlette) -> None:
    """Each connection's handlers see only that connection's request headers."""
    contexts: list[dict[str, Any]] = []

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

                    tool_result = await session.call_tool("echo_context", {"request_id": f"request-{i}"})

                    assert len(tool_result.content) == 1
                    assert isinstance(tool_result.content[0], TextContent)
                    context_data = json.loads(tool_result.content[0].text)
                    contexts.append(context_data)

    assert len(contexts) == 3
    for i, ctx in enumerate(contexts):
        assert ctx["request_id"] == f"request-{i}"
        assert ctx["headers"].get("x-request-id") == f"request-{i}"
        assert ctx["headers"].get("x-custom-value") == f"value-{i}"
        assert ctx["headers"].get("authorization") == f"Bearer token-{i}"


@pytest.mark.anyio
async def test_client_includes_protocol_version_header_after_init(context_app: Starlette) -> None:
    async with (
        make_client(context_app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        init_result = await session.initialize()
        negotiated_version = init_result.protocol_version

        tool_result = await session.call_tool("echo_headers", {})

        assert len(tool_result.content) == 1
        assert isinstance(tool_result.content[0], TextContent)
        headers_data = json.loads(tool_result.content[0].text)

        assert "mcp-protocol-version" in headers_data
        assert headers_data[MCP_PROTOCOL_VERSION_HEADER] == negotiated_version


@pytest.mark.anyio
async def test_server_validates_protocol_version_header(basic_app: Starlette) -> None:
    """An invalid or unsupported protocol version header is rejected with 400; the negotiated one passes."""
    async with make_client(basic_app) as client:
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

        # An unrecognised header value routes to the modern entry, where the
        # validation ladder rejects an envelope-less body at rung 1.
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
        assert response.json()["error"]["code"] == INVALID_PARAMS

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
    async with make_client(basic_app) as client:
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
            assert response.status_code == 200
            assert response.headers.get("Content-Type") == "text/event-stream"


@pytest.mark.anyio
async def test_client_crash_handled(basic_app: Starlette) -> None:
    """A client crashing mid-session does not prevent later clients from connecting."""

    async def bad_client():
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

    mock_sse = ServerSentEvent(event="message", data="", id=None, retry=None)

    write_stream, read_stream = create_context_streams[SessionMessage | Exception](1)

    try:
        result = await transport._handle_sse_event(mock_sse, write_stream)

        assert result is False

        # Nothing should have been written to the stream
        with pytest.raises(TimeoutError):
            with anyio.fail_after(0):
                await read_stream.receive()
    finally:
        await write_stream.aclose()
        await read_stream.aclose()


@pytest.mark.anyio
async def test_close_sse_stream_callback_not_provided_for_old_protocol_version() -> None:
    """close_sse_stream callbacks are only provided for protocol versions that support polling."""
    transport = StreamableHTTPServerTransport(
        "/mcp",
        event_store=SimpleEventStore(),
    )

    mock_message = JSONRPCRequest(jsonrpc="2.0", id="test-1", method="tools/list")
    mock_request = MagicMock()

    session_msg = transport._create_session_message(mock_message, mock_request, "test-request-id", "2025-06-18")

    assert session_msg.metadata is not None
    assert isinstance(session_msg.metadata, ServerMessageMetadata)
    assert session_msg.metadata.close_sse_stream is None
    assert session_msg.metadata.close_standalone_sse_stream is None

    session_msg_new = transport._create_session_message(mock_message, mock_request, "test-request-id-2", "2025-11-25")

    assert session_msg_new.metadata is not None
    assert isinstance(session_msg_new.metadata, ServerMessageMetadata)
    assert session_msg_new.metadata.close_sse_stream is not None
    assert session_msg_new.metadata.close_standalone_sse_stream is not None


@pytest.mark.anyio
async def test_close_sse_stream_callback_not_provided_for_unknown_protocol_version() -> None:
    """close_sse_stream callbacks are withheld when the client's version is unrecognized."""
    transport = StreamableHTTPServerTransport(
        "/mcp",
        event_store=SimpleEventStore(),
    )

    mock_message = JSONRPCRequest(jsonrpc="2.0", id="test-1", method="tools/list")
    mock_request = MagicMock()

    session_msg = transport._create_session_message(mock_message, mock_request, "test-request-id", "zzz")

    assert session_msg.metadata is not None
    assert isinstance(session_msg.metadata, ServerMessageMetadata)
    assert session_msg.metadata.close_sse_stream is None
    assert session_msg.metadata.close_standalone_sse_stream is None


@pytest.mark.anyio
async def test_initialize_with_unknown_protocol_version_gets_no_priming_event(
    event_app: tuple[SimpleEventStore, Starlette],
) -> None:
    """A garbage protocolVersion in initialize params must not trigger priming.

    The priming decision reads the raw body params before any validation, so an
    unrecognized string must gate conservatively (old-client behavior), not
    compare lexicographically past "2025-11-25".
    """
    event_store, app = event_app
    init_request = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "clientInfo": {"name": "test-client", "version": "1.0"},
            "protocolVersion": "zzz",
            "capabilities": {},
        },
        "id": "init-1",
    }
    async with make_client(app) as client:
        response = await client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json=init_request,
        )
        assert response.status_code == 200

    # The store must have seen traffic (the initialize response), but no
    # priming event — priming events are stored with a None payload.
    assert event_store._events
    assert all(message is not None for _, _, message in event_store._events)


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

        metadata = ClientMessageMetadata(
            on_resumption_token_update=on_resumption_token_update,
        )
        result = await session.send_request(
            types.CallToolRequest(params=types.CallToolRequestParams(name="test_tool", arguments={})),
            types.CallToolResult,
            metadata=metadata,
        )
        assert result is not None

        assert len(captured_resumption_tokens) >= 2, (
            f"Server must send priming event before response. "
            f"Expected >= 2 tokens (priming + response), got {len(captured_resumption_tokens)}"
        )
        assert captured_resumption_tokens[0] is not None


@pytest.mark.anyio
async def test_server_close_sse_stream_via_context(
    event_app: tuple[SimpleEventStore, Starlette],
) -> None:
    _, app = event_app

    async with (
        make_client(app) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()

        result = await session.call_tool("tool_with_stream_close", {})

        # The client still receives the complete response via auto-reconnect.
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

        result = await session.call_tool("tool_with_stream_close", {})

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

        result = await session.call_tool("tool_with_stream_close", {})

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

        # The tool sends notification1, closes the stream, then notification2 and notification3.
        result = await session.call_tool("tool_with_multiple_notifications_and_close", {})

        assert "notification1" in notification_data, "Should receive notification1 (sent before close)"
        assert "notification2" in notification_data, "Should receive notification2 (sent after close, replayed)"
        assert "notification3" in notification_data, "Should receive notification3 (sent after close, replayed)"

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

    The tool closes its SSE stream three times, waiting before each next close until the client
    has observed the previous cycle's two new resumption tokens (checkpoint + the reconnect's
    priming event). The priming event is sent only after the server has re-registered the resumed
    stream, so each close is guaranteed to sever a live connection rather than silently no-op —
    the exact token count is a consequence of causality, not timing margins. Reconnect latency is
    pinned by test_streamable_http_client_respects_retry_interval.
    """
    resumption_tokens: list[str] = []
    # After the initial priming token, each completed cycle i adds two tokens — checkpoint_i and
    # the reconnect's priming, in either order — so cycle i is complete at 3 + 2i tokens.
    milestones = {3: anyio.Event(), 5: anyio.Event(), 7: anyio.Event()}

    async def on_resumption_token(token: str) -> None:
        resumption_tokens.append(token)
        milestone = milestones.get(len(resumption_tokens))
        if milestone is not None:
            milestone.set()

    async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        assert params.name == "multi_close_tool"
        for i, milestone in enumerate(milestones.values()):
            await ctx.session.send_log_message(  # pyright: ignore[reportDeprecated]
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
    """The standalone GET stream reconnects with Last-Event-ID after the server closes it.

    Needs the event-store app: the close_standalone_sse_stream callback is only provided when an
    event store is configured and the protocol version is >= 2025-11-25.
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

        result = await session.call_tool("tool_with_standalone_stream_close", {})

        assert result.content[0].type == "text"
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Standalone stream close test done"

        assert "http://notification_1" in received_notifications, (
            f"Should receive notification 1 (sent before GET stream close), got: {received_notifications}"
        )
        assert "http://notification_2" in received_notifications, (
            f"Should receive notification 2 after reconnect, got: {received_notifications}"
        )


@pytest.mark.anyio
async def test_streamable_http_client_does_not_mutate_provided_client(basic_app: Starlette) -> None:
    original_headers = {
        "X-Custom-Header": "custom-value",
        "Authorization": "Bearer test-token",
    }

    async with make_client(basic_app, headers=original_headers) as custom_client:
        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=custom_client) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                result = await session.initialize()
                assert isinstance(result, InitializeResult)

        # If an accept header survives, it must still be the httpx default, not MCP's.
        if "accept" in custom_client.headers:  # pragma: no branch
            assert custom_client.headers.get("accept") == "*/*"
        assert custom_client.headers.get("content-type") != "application/json"

        assert custom_client.headers.get("X-Custom-Header") == "custom-value"
        assert custom_client.headers.get("Authorization") == "Bearer test-token"


@pytest.mark.anyio
async def test_streamable_http_client_mcp_headers_override_defaults(context_app: Starlette) -> None:
    """MCP protocol headers override the httpx client's default headers in actual requests."""
    async with make_client(context_app) as client:
        assert client.headers.get("accept") == "*/*"

        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()

                tool_result = await session.call_tool("echo_headers", {})
                assert len(tool_result.content) == 1
                assert isinstance(tool_result.content[0], TextContent)
                headers_data = json.loads(tool_result.content[0].text)

                assert "accept" in headers_data
                assert "application/json" in headers_data["accept"]
                assert "text/event-stream" in headers_data["accept"]

                assert "content-type" in headers_data
                assert headers_data["content-type"] == "application/json"


@pytest.mark.anyio
async def test_streamable_http_client_preserves_custom_with_mcp_headers(context_app: Starlette) -> None:
    custom_headers = {
        "X-Custom-Header": "custom-value",
        "X-Request-Id": "req-123",
        "Authorization": "Bearer test-token",
    }

    async with make_client(context_app, headers=custom_headers) as client:
        async with streamable_http_client(f"{BASE_URL}/mcp", http_client=client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:  # pragma: no branch
                await session.initialize()

                tool_result = await session.call_tool("echo_headers", {})
                assert len(tool_result.content) == 1
                assert isinstance(tool_result.content[0], TextContent)
                headers_data = json.loads(tool_result.content[0].text)

                assert headers_data.get("x-custom-header") == "custom-value"
                assert headers_data.get("x-request-id") == "req-123"
                assert headers_data.get("authorization") == "Bearer test-token"

                assert "accept" in headers_data
                assert "application/json" in headers_data["accept"]
                assert "text/event-stream" in headers_data["accept"]

                assert "content-type" in headers_data
                assert headers_data["content-type"] == "application/json"


@pytest.mark.anyio
async def test_standalone_stream_teardown_mid_listen_is_not_an_error(caplog: pytest.LogCaptureFixture) -> None:
    """Standalone-stream teardown while the writer is parked in receive() logs no error (SDK-defined)."""
    session_manager = StreamableHTTPSessionManager(
        app=_create_server(),
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    app = Starlette(routes=[Mount("/mcp", app=session_manager.handle_request)])
    notified = anyio.Event()

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        # Only the standalone-stream notification is teed to the handler here.
        assert isinstance(message, types.ResourceUpdatedNotification)
        notified.set()

    async with session_manager.run():
        async with (
            make_client(app) as http_client,
            streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream, message_handler=message_handler) as session,
        ):
            await session.initialize()
            # A notification with no related request rides the GET stream, proving the writer is live.
            await session.call_tool("test_tool_with_standalone_notification", {})
            with anyio.fail_after(5):
                await notified.wait()
            # Tear the standalone stream down while the writer is parked on it.
            (transport,) = session_manager._server_instances.values()  # pyright: ignore[reportPrivateUsage]
            await transport._clean_up_memory_streams(GET_STREAM_KEY)  # pyright: ignore[reportPrivateUsage]
    assert "Error in standalone SSE writer" not in caplog.text


@pytest.mark.anyio
async def test_standalone_stream_teardown_between_dequeues_is_not_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Teardown landing while the standalone writer is between dequeues logs no error.

    SDK-defined: after teardown the writer's next dequeue hits its own closed stream — expected
    disconnect noise. The public surface cannot force this window (the in-process client consumes
    SSE without backpressure), so the test drives the transport's ASGI entry point with a gated `send`.
    """
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    # The GET handler only checks that a read-stream writer exists; it is never written to.
    read_stream_writer, read_stream = create_context_streams[SessionMessage | Exception](0)
    transport._read_stream_writer = read_stream_writer  # pyright: ignore[reportPrivateUsage]

    stream_registered = anyio.Event()

    class SignalingStreams(
        dict[types.RequestId, tuple[MemoryObjectSendStream[EventMessage], MemoryObjectReceiveStream[EventMessage]]]
    ):
        # Only the GET handler inserts here, so any insert is the standalone stream registration.
        def __setitem__(
            self,
            key: types.RequestId,
            value: tuple[MemoryObjectSendStream[EventMessage], MemoryObjectReceiveStream[EventMessage]],
        ) -> None:
            super().__setitem__(key, value)
            stream_registered.set()

    transport._request_streams = SignalingStreams()  # pyright: ignore[reportPrivateUsage]

    gate = anyio.Event()
    sent: list[Message] = []

    async def asgi_send(message: Message) -> None:
        sent.append(message)
        await gate.wait()

    # Never delivers anything, parking the response's disconnect listener.
    disconnect_send, disconnect_receive = anyio.create_memory_object_stream[Message](0)

    async def asgi_receive() -> Message:
        return await disconnect_receive.receive()

    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/mcp",
        "query_string": b"",
        "headers": [(b"accept", b"text/event-stream")],
    }
    notification = types.JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized")

    async with read_stream_writer, read_stream, disconnect_send, disconnect_receive:
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:  # pragma: no branch
                tg.start_soon(transport.handle_request, scope, asgi_receive, asgi_send)
                await stream_registered.wait()
                standalone_send = transport._request_streams[GET_STREAM_KEY][0]  # pyright: ignore[reportPrivateUsage]
                # Zero-buffer rendezvous: once send() returns, the writer has dequeued the event
                # and is blocked forwarding it past the closed gate — the between-dequeues window.
                await standalone_send.send(EventMessage(notification))
                await transport._clean_up_memory_streams(GET_STREAM_KEY)  # pyright: ignore[reportPrivateUsage]
                # Unblock the response; the writer's next dequeue hits its closed stream.
                gate.set()

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 200
    body_chunks = [message for message in sent if message["type"] == "http.response.body"]
    assert b"notifications/initialized" in body_chunks[0]["body"]
    assert body_chunks[-1] == {"type": "http.response.body", "body": b"", "more_body": False}
    assert "Error in standalone SSE writer" not in caplog.text
    assert "Error in standalone SSE response" not in caplog.text
