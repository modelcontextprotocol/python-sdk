import json
import multiprocessing
import socket
import time
from collections.abc import AsyncGenerator, Callable, Coroutine, Generator
from typing import Any
from unittest.mock import Mock

import anyio
import httpx
import pytest
import uvicorn
from inline_snapshot import snapshot
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

import mcp.client.sse
import mcp.types as types
from mcp.client.session import ClientSession
from mcp.client.sse import _extract_session_id_from_endpoint, sse_client
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared._httpx_utils import McpHttpClientFactory
from mcp.shared.context import RequestContext
from mcp.shared.exceptions import McpError
from mcp.shared.message import SessionMessage
from mcp.types import (
    EmptyResult,
    ErrorData,
    Implementation,
    InitializeResult,
    JSONRPCResponse,
    ReadResourceResult,
    ServerCapabilities,
    TextContent,
    TextResourceContents,
    Tool,
)
from tests.test_helpers import wait_for_server

SERVER_NAME = "test_server_for_SSE"


@pytest.fixture
def server_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server_url(server_port: int) -> str:
    return f"http://127.0.0.1:{server_port}"


# Test server implementation
class ServerTest(Server):  # pragma: no cover
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

            raise McpError(error=ErrorData(code=404, message="OOPS! no resource with that URI was found"))

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
        async def handle_call_tool(name: str, args: dict[str, Any]) -> list[TextContent]:
            return [TextContent(type="text", text=f"Called {name}")]


# Test fixtures
def make_server_app() -> Starlette:  # pragma: no cover
    """Create test Starlette app with SSE transport"""
    # Configure security with allowed hosts/origins for testing
    security_settings = TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*"], allowed_origins=["http://127.0.0.1:*", "http://localhost:*"]
    )
    sse = SseServerTransport("/messages/", security_settings=security_settings)
    server = ServerTest()

    async def handle_sse(request: Request) -> Response:
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())
        return Response()

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )

    return app


def run_server(server_port: int) -> None:  # pragma: no cover
    app = make_server_app()
    server = uvicorn.Server(config=uvicorn.Config(app=app, host="127.0.0.1", port=server_port, log_level="error"))
    print(f"starting server on {server_port}")
    server.run()

    # Give server time to start
    while not server.started:
        print("waiting for server to start")
        time.sleep(0.5)


@pytest.fixture()
def server(server_port: int) -> Generator[None, None, None]:
    proc = multiprocessing.Process(target=run_server, kwargs={"server_port": server_port}, daemon=True)
    print("starting process")
    proc.start()

    # Wait for server to be running
    print("waiting for server to start")
    wait_for_server(server_port)

    yield

    print("killing server")
    # Signal the server to stop
    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():  # pragma: no cover
        print("server process failed to terminate")


@pytest.fixture()
async def http_client(server: None, server_url: str) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create test client"""
    async with httpx.AsyncClient(base_url=server_url) as client:
        yield client


# Tests
@pytest.mark.anyio
async def test_raw_sse_connection(http_client: httpx.AsyncClient) -> None:
    """Test the SSE connection establishment simply with an HTTP client."""
    async with anyio.create_task_group():

        async def connection_test() -> None:
            async with http_client.stream("GET", "/sse") as response:
                assert response.status_code == 200
                assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

                line_number = 0
                async for line in response.aiter_lines():  # pragma: no branch
                    if line_number == 0:
                        assert line == "event: endpoint"
                    elif line_number == 1:
                        assert line.startswith("data: /messages/?session_id=")
                    else:
                        return
                    line_number += 1

        # Add timeout to prevent test from hanging if it fails
        with anyio.fail_after(3):
            await connection_test()


@pytest.mark.anyio
async def test_sse_client_basic_connection(server: None, server_url: str) -> None:
    async with sse_client(server_url + "/sse") as streams:
        async with ClientSession(*streams) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == SERVER_NAME

            # Test ping
            ping_result = await session.send_ping()
            assert isinstance(ping_result, EmptyResult)


@pytest.mark.anyio
async def test_sse_client_on_session_created(server: None, server_url: str) -> None:
    captured_session_id: str | None = None

    def on_session_created(session_id: str) -> None:
        nonlocal captured_session_id
        captured_session_id = session_id

    async with sse_client(server_url + "/sse", on_session_created=on_session_created) as streams:
        async with ClientSession(*streams) as session:
            result = await session.initialize()
            assert isinstance(result, InitializeResult)

    assert captured_session_id is not None
    assert len(captured_session_id) > 0


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
    assert _extract_session_id_from_endpoint(endpoint_url) == expected


@pytest.mark.anyio
async def test_sse_client_on_session_created_not_called_when_no_session_id(
    server: None, server_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    callback_mock = Mock()

    def mock_extract(url: str) -> None:
        return None

    monkeypatch.setattr(mcp.client.sse, "_extract_session_id_from_endpoint", mock_extract)

    async with sse_client(server_url + "/sse", on_session_created=callback_mock) as streams:
        async with ClientSession(*streams) as session:
            result = await session.initialize()
            assert isinstance(result, InitializeResult)

    callback_mock.assert_not_called()


@pytest.fixture
async def initialized_sse_client_session(server: None, server_url: str) -> AsyncGenerator[ClientSession, None]:
    async with sse_client(server_url + "/sse", sse_read_timeout=0.5) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            yield session


@pytest.mark.anyio
async def test_sse_client_happy_request_and_response(
    initialized_sse_client_session: ClientSession,
) -> None:
    session = initialized_sse_client_session
    response = await session.read_resource(uri=AnyUrl("foobar://should-work"))
    assert len(response.contents) == 1
    assert isinstance(response.contents[0], TextResourceContents)
    assert response.contents[0].text == "Read should-work"


@pytest.mark.anyio
async def test_sse_client_exception_handling(
    initialized_sse_client_session: ClientSession,
) -> None:
    session = initialized_sse_client_session
    with pytest.raises(McpError, match="OOPS! no resource with that URI was found"):
        await session.read_resource(uri=AnyUrl("xxx://will-not-work"))


class _FailingPostTransport(httpx.AsyncBaseTransport):
    """Passes requests on to the test server, except the message POSTs of one JSON-RPC method, which
    fail with `failure` (a status to answer with, or an exception to raise) the way a rate limiter,
    proxy or network in front of the server would, without reaching it."""

    def __init__(self, method: str, failure: int | Exception) -> None:
        self._inner = httpx.AsyncHTTPTransport()
        self._method = method
        self._failure = failure

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and json.loads(request.content).get("method") == self._method:
            if isinstance(self._failure, Exception):
                raise self._failure
            # A redirect names where to go, so the transport has a redirect to decide on.
            headers = {"location": "/elsewhere"} if 300 <= self._failure < 400 else None
            return httpx.Response(self._failure, headers=headers)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def _failing_post_client_factory(method: str, failure: int | Exception) -> McpHttpClientFactory:
    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=_FailingPostTransport(method, failure), headers=headers, timeout=timeout, auth=auth
        )

    return factory


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [302, 401, 429, 500])
async def test_sse_client_request_post_http_error_reaches_caller_and_session_survives(
    server: None, server_url: str, status_code: int
) -> None:
    """SDK-defined: a non-2xx answer to a request's message POST reaches the waiting caller promptly as a
    JSON-RPC error for that request, and the session stays usable. It used to be swallowed inside the
    transport, leaving the caller waiting forever and every later message unsent (#2110). An
    unfollowed redirect counts: the message never reached the server."""
    factory = _failing_post_client_factory("resources/read", status_code)
    with anyio.fail_after(5):
        async with (
            sse_client(server_url + "/sse", httpx_client_factory=factory) as streams,
            ClientSession(*streams) as session,
        ):
            await session.initialize()

            with pytest.raises(McpError) as exc_info:
                await session.read_resource(uri=AnyUrl("foobar://should-work"))
            assert exc_info.value.error.code == types.INTERNAL_ERROR
            assert exc_info.value.error.message == "Server returned an error response"

            # The session survived the failed POST: the next request round-trips.
            assert isinstance(await session.send_ping(), EmptyResult)


@pytest.mark.anyio
async def test_sse_client_request_post_404_reports_session_terminated(server: None, server_url: str) -> None:
    """SDK-defined: a 404 answer to a request's message POST, while the endpoint URL carries a session id,
    means the server no longer knows the session: the caller gets "Session terminated"
    (INVALID_REQUEST) and can reconnect."""
    factory = _failing_post_client_factory("resources/read", 404)
    with anyio.fail_after(5):
        async with (
            sse_client(server_url + "/sse", httpx_client_factory=factory) as streams,
            ClientSession(*streams) as session,
        ):
            await session.initialize()

            with pytest.raises(McpError) as exc_info:
                await session.read_resource(uri=AnyUrl("foobar://should-work"))
            assert exc_info.value.error.code == types.INVALID_REQUEST
            assert exc_info.value.error.message == "Session terminated"


@pytest.mark.anyio
async def test_sse_client_request_post_network_error_reaches_caller_and_session_survives(
    server: None, server_url: str
) -> None:
    """SDK-defined: a request's message POST that fails without a response reaches the waiting caller
    promptly as a CONNECTION_CLOSED error for that request, and the session stays usable (#2110)."""
    factory = _failing_post_client_factory("resources/read", httpx.ConnectError("connection refused"))
    with anyio.fail_after(5):
        async with (
            sse_client(server_url + "/sse", httpx_client_factory=factory) as streams,
            ClientSession(*streams) as session,
        ):
            await session.initialize()

            with pytest.raises(McpError) as exc_info:
                await session.read_resource(uri=AnyUrl("foobar://should-work"))
            assert exc_info.value.error.code == types.CONNECTION_CLOSED
            assert exc_info.value.error.message == "Failed to send message: connection refused"

            # The session survived the failed POST: the next request round-trips.
            assert isinstance(await session.send_ping(), EmptyResult)


@pytest.mark.anyio
async def test_sse_client_notification_post_failure_keeps_session_usable(server: None, server_url: str) -> None:
    """SDK-defined: a failed message POST of a notification has no waiter to resolve, so it is only
    logged, and the session stays usable (#2110: it used to leave every later message unsent)."""
    factory = _failing_post_client_factory("notifications/roots/list_changed", 500)
    with anyio.fail_after(5):
        async with (
            sse_client(server_url + "/sse", httpx_client_factory=factory) as streams,
            ClientSession(*streams) as session,
        ):
            await session.initialize()

            await session.send_roots_list_changed()

            assert isinstance(await session.send_ping(), EmptyResult)


@pytest.mark.anyio
@pytest.mark.skip("this test highlights a possible bug in SSE read timeout exception handling")
async def test_sse_client_timeout(  # pragma: no cover
    initialized_sse_client_session: ClientSession,
) -> None:
    session = initialized_sse_client_session

    # sanity check that normal, fast responses are working
    response = await session.read_resource(uri=AnyUrl("foobar://1"))
    assert isinstance(response, ReadResourceResult)

    with anyio.move_on_after(3):
        with pytest.raises(McpError, match="Read timed out"):
            response = await session.read_resource(uri=AnyUrl("slow://2"))
            # we should receive an error here
        return

    pytest.fail("the client should have timed out and returned an error already")


def run_mounted_server(server_port: int) -> None:  # pragma: no cover
    app = make_server_app()
    main_app = Starlette(routes=[Mount("/mounted_app", app=app)])
    server = uvicorn.Server(config=uvicorn.Config(app=main_app, host="127.0.0.1", port=server_port, log_level="error"))
    print(f"starting server on {server_port}")
    server.run()

    # Give server time to start
    while not server.started:
        print("waiting for server to start")
        time.sleep(0.5)


@pytest.fixture()
def mounted_server(server_port: int) -> Generator[None, None, None]:
    proc = multiprocessing.Process(target=run_mounted_server, kwargs={"server_port": server_port}, daemon=True)
    print("starting process")
    proc.start()

    # Wait for server to be running
    print("waiting for server to start")
    wait_for_server(server_port)

    yield

    print("killing server")
    # Signal the server to stop
    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():  # pragma: no cover
        print("server process failed to terminate")


@pytest.mark.anyio
async def test_sse_client_basic_connection_mounted_app(mounted_server: None, server_url: str) -> None:
    async with sse_client(server_url + "/mounted_app/sse") as streams:
        async with ClientSession(*streams) as session:
            # Test initialization
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.serverInfo.name == SERVER_NAME

            # Test ping
            ping_result = await session.send_ping()
            assert isinstance(ping_result, EmptyResult)


# Test server with request context that returns headers in the response
class RequestContextServer(Server[object, Request]):  # pragma: no cover
    def __init__(self):
        super().__init__("request_context_server")

        @self.call_tool()
        async def handle_call_tool(name: str, args: dict[str, Any]) -> list[TextContent]:
            headers_info = {}
            context = self.request_context
            if context.request:
                headers_info = dict(context.request.headers)

            if name == "echo_headers":
                return [TextContent(type="text", text=json.dumps(headers_info))]
            elif name == "echo_context":
                context_data = {
                    "request_id": args.get("request_id"),
                    "headers": headers_info,
                }
                return [TextContent(type="text", text=json.dumps(context_data))]

            return [TextContent(type="text", text=f"Called {name}")]

        @self.list_tools()
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


def run_context_server(server_port: int) -> None:  # pragma: no cover
    """Run a server that captures request context"""
    # Configure security with allowed hosts/origins for testing
    security_settings = TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*"], allowed_origins=["http://127.0.0.1:*", "http://localhost:*"]
    )
    sse = SseServerTransport("/messages/", security_settings=security_settings)
    context_server = RequestContextServer()

    async def handle_sse(request: Request) -> Response:
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await context_server.run(streams[0], streams[1], context_server.create_initialization_options())
        return Response()

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )

    server = uvicorn.Server(config=uvicorn.Config(app=app, host="127.0.0.1", port=server_port, log_level="error"))
    print(f"starting context server on {server_port}")
    server.run()


@pytest.fixture()
def context_server(server_port: int) -> Generator[None, None, None]:
    """Fixture that provides a server with request context capture"""
    proc = multiprocessing.Process(target=run_context_server, kwargs={"server_port": server_port}, daemon=True)
    print("starting context server process")
    proc.start()

    # Wait for server to be running
    print("waiting for context server to start")
    wait_for_server(server_port)

    yield

    print("killing context server")
    proc.kill()
    proc.join(timeout=2)
    if proc.is_alive():  # pragma: no cover
        print("context server process failed to terminate")


@pytest.mark.anyio
async def test_request_context_propagation(context_server: None, server_url: str) -> None:
    """Test that request context is properly propagated through SSE transport."""
    # Test with custom headers
    custom_headers = {
        "Authorization": "Bearer test-token",
        "X-Custom-Header": "test-value",
        "X-Trace-Id": "trace-123",
    }

    async with sse_client(server_url + "/sse", headers=custom_headers) as (
        read_stream,
        write_stream,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            # Initialize the session
            result = await session.initialize()
            assert isinstance(result, InitializeResult)

            # Call the tool that echoes headers back
            tool_result = await session.call_tool("echo_headers", {})

            # Parse the JSON response

            assert len(tool_result.content) == 1
            headers_data = json.loads(tool_result.content[0].text if tool_result.content[0].type == "text" else "{}")

            # Verify headers were propagated
            assert headers_data.get("authorization") == "Bearer test-token"
            assert headers_data.get("x-custom-header") == "test-value"
            assert headers_data.get("x-trace-id") == "trace-123"


@pytest.mark.anyio
async def test_request_context_isolation(context_server: None, server_url: str) -> None:
    """Test that request contexts are isolated between different SSE clients."""
    contexts: list[dict[str, Any]] = []

    # Create multiple clients with different headers
    for i in range(3):
        headers = {"X-Request-Id": f"request-{i}", "X-Custom-Value": f"value-{i}"}

        async with sse_client(server_url + "/sse", headers=headers) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Call the tool that echoes context
                tool_result = await session.call_tool("echo_context", {"request_id": f"request-{i}"})

                assert len(tool_result.content) == 1
                context_data = json.loads(
                    tool_result.content[0].text if tool_result.content[0].type == "text" else "{}"
                )
                contexts.append(context_data)

    # Verify each request had its own context
    assert len(contexts) == 3
    for i, ctx in enumerate(contexts):
        assert ctx["request_id"] == f"request-{i}"
        assert ctx["headers"].get("x-request-id") == f"request-{i}"
        assert ctx["headers"].get("x-custom-value") == f"value-{i}"


def test_sse_message_id_coercion():
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
def test_sse_server_transport_endpoint_validation(endpoint: str, expected_result: str | type[Exception]):
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


@pytest.mark.anyio
async def test_sse_client_handles_empty_keepalive_pings() -> None:
    """Test that SSE client properly handles empty data lines (keep-alive pings).

    Per the MCP spec (Streamable HTTP transport): "The server SHOULD immediately
    send an SSE event consisting of an event ID and an empty data field in order
    to prime the client to reconnect."

    The event stream served here carries an endpoint event, an empty "message"
    event (the case under test), then a real response; the client must skip the
    empty one and deliver the response.
    """
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
    event_stream = (
        "event: endpoint\ndata: /messages/?session_id=abc123\n\n"
        "event: message\ndata: \n\n"
        f"event: message\ndata: {response_json}\n\n"
    )

    def serve(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/sse"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=event_stream)

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(serve))

    with anyio.fail_after(5):
        async with sse_client("http://test/sse", httpx_client_factory=factory) as (read_stream, _):
            msg = await read_stream.receive()
            assert isinstance(msg, SessionMessage)
            assert isinstance(msg.message.root, types.JSONRPCResponse)
            assert msg.message.root.id == 1


@pytest.mark.anyio
async def test_sse_client_follows_redirect_within_origin_on_connect() -> None:
    """SDK-defined: a redirect of the SSE GET that stays on the endpoint's origin is followed by
    the transport itself, with a client left at httpx's no-follow default."""
    received: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        received.append(str(request.url))
        if request.url.path == "/sse":
            return httpx.Response(307, headers={"location": "/sse/"})
        assert request.url.path == "/sse/"
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, text="event: endpoint\ndata: /messages/\n\n"
        )

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(serve))

    with anyio.fail_after(5):
        async with sse_client("http://test/sse", httpx_client_factory=factory):
            pass

    assert received == ["http://test/sse", "http://test/sse/"]


@pytest.mark.anyio
async def test_sse_client_does_not_follow_redirect_to_another_origin_on_connect() -> None:
    """SDK-defined: a redirect of the SSE GET to another origin is not followed, even with a client
    configured to follow redirects: connecting fails with HTTPStatusError for the redirect response
    (raised inside sse_client's task group) and that origin is never contacted."""
    received: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        received.append(str(request.url))
        return httpx.Response(307, headers={"location": "http://other.example/sse"})

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(serve), follow_redirects=True)

    with anyio.fail_after(5):
        with pytest.raises(Exception) as exc_info:
            async with sse_client("http://test/sse", httpx_client_factory=factory):
                pytest.fail("should not connect")  # pragma: no cover

    assert exc_info.group_contains(httpx.HTTPStatusError, match="307 Temporary Redirect")
    assert received == ["http://test/sse"]


def _mock_client_factory(
    serve: Callable[[httpx.Request], Coroutine[None, None, httpx.Response]],
) -> McpHttpClientFactory:
    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(serve))

    return factory


@pytest.mark.anyio
async def test_sse_client_post_404_without_session_endpoint_keeps_generic_error() -> None:
    """SDK-defined: a 404 answer to a request's message POST when the endpoint URL carries no session id
    keeps the generic error: with no session to expire, "Session terminated" would be wrong. The
    endpoint is scripted because `SseServerTransport` always issues a session id."""

    async def event_stream() -> AsyncGenerator[bytes, None]:
        yield b"event: endpoint\ndata: /messages/\n\n"
        await anyio.sleep_forever()

    async def serve(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=event_stream())
        return httpx.Response(404)

    with anyio.fail_after(5):
        async with (
            sse_client("http://test/sse", httpx_client_factory=_mock_client_factory(serve)) as streams,
            ClientSession(*streams) as session,
        ):
            with pytest.raises(McpError) as exc_info:
                await session.send_ping()
            assert exc_info.value.error.code == types.INTERNAL_ERROR
            assert exc_info.value.error.message == "Server returned an error response"


@pytest.mark.anyio
async def test_sse_client_failed_request_post_does_not_hold_up_reply_to_server_request() -> None:
    """SDK-defined: the error for a request's failed message POST is delivered without holding up the
    messages after it. ClientSession answers a server request inline in its receive loop, so its reply
    can be waiting on the transport exactly when that error needs the receive loop: delivering it from
    the loop that sends messages would leave the two waiting on each other forever."""
    list_tools_posted = anyio.Event()
    roots_listed = anyio.Event()
    reply_posted = anyio.Event()

    async def event_stream() -> AsyncGenerator[bytes, None]:
        yield b"event: endpoint\ndata: /messages/?session_id=abc123\n\n"
        await list_tools_posted.wait()
        # A server request arrives while the client's tools/list POST is in flight.
        server_request = types.JSONRPCRequest(jsonrpc="2.0", id="server-1", method="roots/list")
        yield f"event: message\ndata: {server_request.model_dump_json()}\n\n".encode()
        await anyio.sleep_forever()

    async def serve(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=event_stream())
        message = json.loads(request.content)
        if message.get("method") == "tools/list":
            list_tools_posted.set()
            # Fail once the client is answering the server request: its reply then waits behind this POST.
            await roots_listed.wait()
            return httpx.Response(429)
        assert message == {"jsonrpc": "2.0", "id": "server-1", "result": {"roots": []}}
        reply_posted.set()
        return httpx.Response(202)

    async def list_roots(context: RequestContext[ClientSession, Any]) -> types.ListRootsResult:
        roots_listed.set()
        return types.ListRootsResult(roots=[])

    with anyio.fail_after(5):
        async with (
            sse_client("http://test/sse", httpx_client_factory=_mock_client_factory(serve)) as streams,
            ClientSession(*streams, list_roots_callback=list_roots) as session,
        ):
            with pytest.raises(McpError) as exc_info:
                await session.list_tools()
            assert exc_info.value.error.message == "Server returned an error response"

            await reply_posted.wait()


@pytest.mark.anyio
async def test_sse_client_post_error_after_reader_closed_is_contained() -> None:
    """SDK-defined: a failed request POST whose error can no longer be delivered, because the server's
    SSE stream already ended and closed the read stream, is contained: later messages are still sent
    and the transport closes cleanly. Raw streams, because a ClientSession stops sending once its read
    stream closes."""
    stream_done = anyio.Event()
    release_post = anyio.Event()
    second_post = anyio.Event()

    async def event_stream() -> AsyncGenerator[bytes, None]:
        yield b"event: endpoint\ndata: /messages/?session_id=abc123\n\n"
        await stream_done.wait()

    async def serve(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=event_stream())
        if json.loads(request.content).get("method") == "ping":
            await release_post.wait()
            return httpx.Response(500)
        second_post.set()
        return httpx.Response(202)

    ping = types.JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    initialized = types.JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized")
    with anyio.fail_after(5):
        async with sse_client("http://test/sse", httpx_client_factory=_mock_client_factory(serve)) as (
            read_stream,
            write_stream,
        ):
            await write_stream.send(SessionMessage(types.JSONRPCMessage(ping)))
            stream_done.set()
            assert [message async for message in read_stream] == []

            release_post.set()
            await write_stream.send(SessionMessage(types.JSONRPCMessage(initialized)))
            await second_post.wait()
