"""Tests for the SSE client and server transports, driven entirely in process."""

import gc
import json
from collections.abc import AsyncGenerator, Iterable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import anyio
import httpx
import pytest
from httpx_sse import ServerSentEvent
from inline_snapshot import snapshot
from pydantic import AnyUrl
from sse_starlette.sse import AppStatus
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

import mcp.client.sse
import mcp.types as types
from mcp.client.session import ClientSession
from mcp.client.sse import _extract_session_id_from_endpoint, sse_client
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.sse import SseServerTransport
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared._httpx_utils import McpHttpClientFactory
from mcp.shared.exceptions import McpError
from mcp.types import (
    CallToolResult,
    EmptyResult,
    ErrorData,
    Implementation,
    InitializeResult,
    JSONRPCResponse,
    ServerCapabilities,
    TextContent,
    TextResourceContents,
    Tool,
)
from tests.interaction.transports import StreamingASGITransport

SERVER_NAME = "test_server_for_SSE"

# The in-process app is mounted at this origin purely so URLs are well-formed; nothing listens here.
BASE_URL = "http://127.0.0.1:8000"

# v1's HTTP server transports leak a handful of anyio memory streams on teardown when run in
# process; the old subprocess harness never observed them. The interaction suite registers the
# same two scoped filters globally from tests/interaction/conftest.py (see the comment there),
# but they only take effect when that package's conftest is loaded; these markers keep the tests
# themselves passing in isolated runs. Markers are item-scoped, so the autouse
# `_collect_leaked_streams` fixture below garbage-collects each test's leaks inside its own
# teardown, where these filters apply; without it, leaks GC'd at session cleanup escape the
# scoped ignores. The filters are scoped to anyio's MemoryObject*Stream leak signature so an
# unrelated leak still fails the suite.
pytestmark = [
    pytest.mark.filterwarnings("ignore:.*MemoryObject(Send|Receive)Stream:pytest.PytestUnraisableExceptionWarning"),
    pytest.mark.filterwarnings("ignore:.*MemoryObject(Send|Receive)Stream:ResourceWarning"),
]


@pytest.fixture(autouse=True)
def _collect_leaked_streams() -> Iterator[None]:
    """Garbage-collect each test's leaked memory streams inside its own teardown.

    The filterwarnings marks above only apply while a test in this file is the
    active warning context. The leaked streams sit in reference cycles, so without
    a forced collection their deallocator warnings fire wherever the garbage
    collector happens to run next: during an unrelated test (failing it, since the
    global ``filterwarnings = ["error"]`` has no ignore there) or at pytest's
    session-unconfigure unraisable sweep (exit code 1 after all tests passed when
    running without xdist, e.g. ``-n 0`` for ``--pdb`` debugging).
    """
    yield
    gc.collect()


@pytest.fixture(autouse=True)
def _reset_sse_starlette_exit_event() -> Iterator[None]:
    """Reset sse-starlette's module-global exit Event around each test.

    sse-starlette <3.0 (allowed by this branch's dependency floor; CI's lowest-direct leg
    installs it) stores an `anyio.Event` on the `AppStatus` class the first time an
    `EventSourceResponse` runs; that Event is bound to the test's event loop and breaks every
    subsequent in-process SSE response. sse-starlette 3.x switched to a ContextVar and has no
    such attribute. Resetting on both sides of the test keeps this module immune to a stale
    Event left behind by an earlier test on the same worker as well as cleaning up after its
    own. This mirrors the autouse fixture in tests/interaction/conftest.py, which guards the
    interaction suite the same way.
    """
    if hasattr(AppStatus, "should_exit_event"):  # pragma: no branch
        # setattr keeps pyright happy: the locked sse-starlette 3.x has no such attribute.
        setattr(AppStatus, "should_exit_event", None)  # pragma: lax no cover
    yield
    if hasattr(AppStatus, "should_exit_event"):  # pragma: no branch
        setattr(AppStatus, "should_exit_event", None)  # pragma: lax no cover


def in_process_client_factory(app: Starlette) -> McpHttpClientFactory:
    """An httpx_client_factory for sse_client whose clients are served in process by `app`."""

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        # The SSE GET runs until it observes a disconnect, so the bridge must let the
        # application drain on close rather than cancelling it. follow_redirects matches
        # create_mcp_http_client, the factory this one stands in for.
        return httpx.AsyncClient(
            transport=StreamingASGITransport(app, cancel_on_close=False),
            base_url=BASE_URL,
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=True,
        )

    return factory


def make_test_server() -> Server[object, Request]:
    """A server whose read_resource handler answers foobar:// URIs and 404s everything else."""
    server: Server[object, Request] = Server(SERVER_NAME)

    @server.read_resource()
    async def handle_read_resource(uri: AnyUrl) -> Iterable[ReadResourceContents]:
        if uri.scheme == "foobar":
            return [ReadResourceContents(content=f"Read {uri.host}", mime_type="text/plain")]
        raise McpError(error=ErrorData(code=404, message="OOPS! no resource with that URI was found"))

    return server


def make_app(server: Server[Any, Any]) -> Starlette:
    """Mount `server` on a Starlette app exposing the SSE transport at /sse and /messages/."""
    # DNS-rebinding protection validates Host/Origin headers against a network attack that cannot
    # exist for an in-process app; the transport security behaviour itself is pinned by
    # tests/server/test_sse_security.py.
    sse = SseServerTransport(
        "/messages/", security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )

    async def handle_sse(request: Request) -> Response:
        async with sse.connect_sse(request.scope, request.receive, request._send) as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
        return Response()

    return Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )


def make_server_app() -> Starlette:
    return make_app(make_test_server())


@pytest.mark.anyio
async def test_raw_sse_connection() -> None:
    """The SSE GET responds 200 with an event-stream content type, announcing the session
    endpoint as its first event."""
    http_client = httpx.AsyncClient(
        transport=StreamingASGITransport(make_server_app(), cancel_on_close=False), base_url=BASE_URL
    )

    with anyio.fail_after(5):
        async with http_client, http_client.stream("GET", "/sse") as response:
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            lines = response.aiter_lines()
            assert await anext(lines) == "event: endpoint"
            assert (await anext(lines)).startswith("data: /messages/?session_id=")


@pytest.mark.anyio
async def test_sse_client_basic_connection() -> None:
    """A client initializes against, and pings, a server over the SSE transport."""
    factory = in_process_client_factory(make_server_app())
    async with sse_client(f"{BASE_URL}/sse", httpx_client_factory=factory) as streams:
        async with ClientSession(*streams) as session:
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == SERVER_NAME

            ping_result = await session.send_ping()
            assert isinstance(ping_result, EmptyResult)


@pytest.mark.anyio
async def test_sse_client_on_session_created() -> None:
    """The session-created callback receives the new session ID before sse_client yields."""
    factory = in_process_client_factory(make_server_app())
    captured: list[str] = []

    async with sse_client(
        f"{BASE_URL}/sse", httpx_client_factory=factory, on_session_created=captured.append
    ) as streams:
        async with ClientSession(*streams) as session:
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            # Callback fires when the endpoint event arrives, before sse_client yields.
            assert len(captured) == 1
            assert len(captured[0]) > 0


@pytest.mark.parametrize(
    "endpoint_url,expected",
    [
        ("/messages?sessionId=abc123", "abc123"),
        ("/messages?session_id=def456", "def456"),
        ("/messages?sessionId=abc&session_id=def", "abc"),
        ("/messages?other=value", None),
        ("/messages", None),
        ("", None),
    ],
)
def test_extract_session_id_from_endpoint(endpoint_url: str, expected: str | None) -> None:
    """The session ID is read from the endpoint URL's sessionId/session_id query parameters."""
    assert _extract_session_id_from_endpoint(endpoint_url) == expected


@pytest.mark.anyio
async def test_sse_client_on_session_created_not_called_when_no_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """No session-created callback fires when the endpoint URL carries no session ID."""
    factory = in_process_client_factory(make_server_app())
    callback_mock = Mock()

    def mock_extract(url: str) -> None:
        return None

    monkeypatch.setattr(mcp.client.sse, "_extract_session_id_from_endpoint", mock_extract)

    async with sse_client(f"{BASE_URL}/sse", httpx_client_factory=factory, on_session_created=callback_mock) as streams:
        async with ClientSession(*streams) as session:
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            # Callback would have fired by now (endpoint event arrives before
            # sse_client yields); if it hasn't, it won't.
            callback_mock.assert_not_called()


@pytest.fixture
async def initialized_sse_client_session() -> AsyncGenerator[ClientSession, None]:
    factory = in_process_client_factory(make_server_app())
    async with sse_client(f"{BASE_URL}/sse", httpx_client_factory=factory) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            yield session


@pytest.mark.anyio
async def test_sse_client_happy_request_and_response(
    initialized_sse_client_session: ClientSession,
) -> None:
    """A resource read round-trips its arguments and the handler's content over SSE."""
    session = initialized_sse_client_session
    response = await session.read_resource(uri=AnyUrl("foobar://should-work"))
    assert len(response.contents) == 1
    assert isinstance(response.contents[0], TextResourceContents)
    assert response.contents[0].text == "Read should-work"


@pytest.mark.anyio
async def test_sse_client_exception_handling(
    initialized_sse_client_session: ClientSession,
) -> None:
    """A server-side McpError reaches the client with its message intact."""
    session = initialized_sse_client_session
    with pytest.raises(McpError, match="OOPS! no resource with that URI was found"):
        await session.read_resource(uri=AnyUrl("xxx://will-not-work"))


@pytest.mark.anyio
async def test_sse_client_basic_connection_mounted_app() -> None:
    """The SSE transport works unchanged when its app is mounted under a sub-path."""
    main_app = Starlette(routes=[Mount("/mounted_app", app=make_server_app())])
    factory = in_process_client_factory(main_app)

    async with sse_client(f"{BASE_URL}/mounted_app/sse", httpx_client_factory=factory) as streams:
        async with ClientSession(*streams) as session:
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == SERVER_NAME

            ping_result = await session.send_ping()
            assert isinstance(ping_result, EmptyResult)


def make_context_server() -> Server[object, Request]:
    """A server whose tools echo back the request headers seen via the request context."""
    server: Server[object, Request] = Server("request_context_server")

    @server.call_tool()
    async def handle_call_tool(name: str, args: dict[str, Any]) -> CallToolResult:
        assert name in ("echo_headers", "echo_context")
        ctx = server.request_context
        assert ctx.request is not None
        headers_info = dict(ctx.request.headers)

        if name == "echo_headers":
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(headers_info))])

        context_data = {
            "request_id": args.get("request_id"),
            "headers": headers_info,
        }
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(context_data))])

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return [
            Tool(
                name="echo_headers",
                description="Echoes request headers",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="echo_context",
                description="Echoes request context",
                inputSchema={
                    "type": "object",
                    "properties": {"request_id": {"type": "string"}},
                    "required": ["request_id"],
                },
            ),
        ]

    return server


def make_context_server_app() -> Starlette:
    return make_app(make_context_server())


@pytest.mark.anyio
async def test_request_context_propagation() -> None:
    """Custom HTTP headers on the SSE connection are visible to server handlers via the request context."""
    factory = in_process_client_factory(make_context_server_app())

    custom_headers = {
        "Authorization": "Bearer test-token",
        "X-Custom-Header": "test-value",
        "X-Trace-Id": "trace-123",
    }

    async with sse_client(f"{BASE_URL}/sse", httpx_client_factory=factory, headers=custom_headers) as streams:
        async with ClientSession(*streams) as session:
            result = await session.initialize()
            assert isinstance(result, InitializeResult)

            tool_result = await session.call_tool("echo_headers", {})

            assert len(tool_result.content) == 1
            content = tool_result.content[0]
            assert isinstance(content, TextContent)
            headers_data = json.loads(content.text)

            assert headers_data.get("authorization") == "Bearer test-token"
            assert headers_data.get("x-custom-header") == "test-value"
            assert headers_data.get("x-trace-id") == "trace-123"


@pytest.mark.anyio
async def test_request_context_isolation() -> None:
    """Each SSE connection's handlers see only that connection's request headers."""
    factory = in_process_client_factory(make_context_server_app())

    # Connect three clients in turn, each with its own headers. Each connection is
    # verified inside its own block: on Python 3.11 the line tracer is lost once an
    # async-with teardown throws (python/cpython#106749), so statements placed after
    # this loop would be reported uncovered on some matrix cells. The loop's exit
    # arc fires after the final teardown and sits in the same shadow, hence the
    # branch exclusion.
    for i in range(3):  # pragma: no branch
        headers = {"X-Request-Id": f"request-{i}", "X-Custom-Value": f"value-{i}"}

        async with sse_client(f"{BASE_URL}/sse", httpx_client_factory=factory, headers=headers) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()

                tool_result = await session.call_tool("echo_context", {"request_id": f"request-{i}"})

                assert len(tool_result.content) == 1
                content = tool_result.content[0]
                assert isinstance(content, TextContent)
                ctx = json.loads(content.text)
                assert ctx["request_id"] == f"request-{i}"
                assert ctx["headers"].get("x-request-id") == f"request-{i}"
                assert ctx["headers"].get("x-custom-value") == f"value-{i}"


def test_sse_message_id_coercion() -> None:
    """Previously, the `RequestId` would coerce a string that looked like an integer into an integer.

    See <https://github.com/modelcontextprotocol/python-sdk/pull/851> for more details.

    As per the JSON-RPC 2.0 specification, the id in the response object needs to be the same type as the id in the
    request object. In other words, we can't perform the coercion.

    See <https://www.jsonrpc.org/specification#response_object> for more details.
    """
    json_message = '{"jsonrpc": "2.0", "id": "123", "method": "ping", "params": null}'
    msg = types.JSONRPCMessage.model_validate_json(json_message)
    assert msg == snapshot(types.JSONRPCMessage(root=types.JSONRPCRequest(method="ping", jsonrpc="2.0", id="123")))

    json_message = '{"jsonrpc": "2.0", "id": 123, "method": "ping", "params": null}'
    msg = types.JSONRPCMessage.model_validate_json(json_message)
    assert msg == snapshot(types.JSONRPCMessage(root=types.JSONRPCRequest(method="ping", jsonrpc="2.0", id=123)))


@pytest.mark.parametrize(
    "endpoint, expected_result",
    [
        # Valid endpoints - should normalize and work
        ("/messages/", "/messages/"),
        ("messages/", "/messages/"),
        ("/", "/"),
        # Invalid endpoints - should raise ValueError
        ("http://example.com/messages/", ValueError),
        ("//example.com/messages/", ValueError),
        ("ftp://example.com/messages/", ValueError),
        ("/messages/?param=value", ValueError),
        ("/messages/#fragment", ValueError),
    ],
)
def test_sse_server_transport_endpoint_validation(endpoint: str, expected_result: str | type[Exception]) -> None:
    """Test that SseServerTransport properly validates and normalizes endpoints."""
    if isinstance(expected_result, type):
        # Test invalid endpoints that should raise an exception
        with pytest.raises(expected_result, match="is not a relative path.*expecting a relative path"):
            SseServerTransport(endpoint)
    else:
        # Test valid endpoints that should normalize correctly
        sse = SseServerTransport(endpoint)
        assert sse._endpoint == expected_result
        assert sse._endpoint.startswith("/")


# ResourceWarning filter: When mocking aconnect_sse, the sse_client's internal task
# group doesn't receive proper cancellation signals, so the sse_reader task's finally
# block (which closes read_stream_writer) doesn't execute. This is a test artifact -
# the actual code path (`if not sse.data: continue`) IS exercised and works correctly.
# Production code with real SSE connections cleans up properly.
@pytest.mark.filterwarnings("ignore::ResourceWarning")
@pytest.mark.anyio
async def test_sse_client_handles_empty_keepalive_pings() -> None:
    """Test that SSE client properly handles empty data lines (keep-alive pings).

    Per the MCP spec (Streamable HTTP transport): "The server SHOULD immediately
    send an SSE event consisting of an event ID and an empty data field in order
    to prime the client to reconnect."

    This test mocks the SSE event stream to include empty "message" events and
    verifies the client skips them without crashing.
    """
    # Build a proper JSON-RPC response using types (not hardcoded strings)
    init_result = InitializeResult(
        protocolVersion="2024-11-05",
        capabilities=ServerCapabilities(),
        serverInfo=Implementation(name="test", version="1.0"),
    )
    response = JSONRPCResponse(
        jsonrpc="2.0",
        id=1,
        result=init_result.model_dump(by_alias=True, exclude_none=True),
    )
    response_json = response.model_dump_json(by_alias=True, exclude_none=True)

    # Create mock SSE events using httpx_sse's ServerSentEvent
    async def mock_aiter_sse() -> AsyncGenerator[ServerSentEvent, None]:
        # First: endpoint event
        yield ServerSentEvent(event="endpoint", data="/messages/?session_id=abc123")
        # Empty data keep-alive ping - this is what we're testing
        yield ServerSentEvent(event="message", data="")
        # Real JSON-RPC response
        yield ServerSentEvent(event="message", data=response_json)

    mock_event_source = MagicMock()
    mock_event_source.aiter_sse.return_value = mock_aiter_sse()
    mock_event_source.response = MagicMock()
    mock_event_source.response.raise_for_status = MagicMock()

    mock_aconnect_sse = MagicMock()
    mock_aconnect_sse.__aenter__ = AsyncMock(return_value=mock_event_source)
    mock_aconnect_sse.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=MagicMock(status_code=200, raise_for_status=MagicMock()))

    with (
        patch("mcp.client.sse.create_mcp_http_client", return_value=mock_client),
        patch("mcp.client.sse.aconnect_sse", return_value=mock_aconnect_sse),
    ):
        async with sse_client("http://test/sse") as (read_stream, _):
            # Read the message - should skip the empty one and get the real response
            msg = await read_stream.receive()
            # If we get here without error, the empty message was skipped successfully
            assert not isinstance(msg, Exception)
            assert isinstance(msg.message.root, types.JSONRPCResponse)
            assert msg.message.root.id == 1


@pytest.mark.anyio
async def test_sse_session_cleanup_on_disconnect() -> None:
    """Regression test for https://github.com/modelcontextprotocol/python-sdk/issues/1227

    When a client disconnects, the server should remove the session from
    _read_stream_writers. Without this cleanup, stale sessions accumulate and
    POST requests to disconnected sessions return 202 Accepted followed by a
    ClosedResourceError when the server tries to write to the dead stream.
    """
    factory = in_process_client_factory(make_server_app())
    captured: list[str] = []

    # Connect a client session, then disconnect
    async with sse_client(
        f"{BASE_URL}/sse", httpx_client_factory=factory, on_session_created=captured.append
    ) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()

    # After disconnect, POST to the stale session should return 404
    # (not 202 as it did before the fix)
    async with factory() as client:
        response = await client.post(
            f"/messages/?session_id={captured[0]}",
            json={"jsonrpc": "2.0", "method": "ping", "id": 99},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 404
