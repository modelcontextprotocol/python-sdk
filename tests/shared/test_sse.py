import json
import math
import multiprocessing
import socket
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from datetime import timedelta
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
from mcp.shared.context import RequestContext
from mcp.shared.exceptions import McpError
from mcp.shared.message import SessionMessage
from mcp.types import (
    CallToolResult,
    EmptyResult,
    ErrorData,
    Implementation,
    InitializeResult,
    JSONRPCResponse,
    ListRootsResult,
    ListToolsResult,
    ReadResourceResult,
    ServerCapabilities,
    TextContent,
    TextResourceContents,
    Tool,
    ToolsCapability,
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


class _RejectingSseServer:
    """An in-process SSE server that answers on its event stream and fails chosen message POSTs."""

    def __init__(self, endpoint: str = "/messages/?session_id=abc123") -> None:
        self.endpoint = endpoint
        self.post_status: dict[str, int] = {}
        self.post_error: dict[str, Exception] = {}
        self.before_rejecting: Callable[[], Awaitable[None]] | None = None
        self._events, self._events_reader = anyio.create_memory_object_stream[str](math.inf)

    async def __aenter__(self) -> "_RejectingSseServer":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self._events.close()
        self._events_reader.close()

    def client_factory(
        self,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def push(self, message: dict[str, Any]) -> None:
        self._events.send_nowait(f"event: message\ndata: {json.dumps(message)}\n\n")

    async def _event_stream(self) -> AsyncGenerator[bytes, None]:
        yield f"event: endpoint\ndata: {self.endpoint}\n\n".encode()
        async for event in self._events_reader:  # pragma: no branch
            yield event.encode()

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=self._event_stream())
        message = json.loads(request.content)
        method = message.get("method")
        if method in self.post_error:
            raise self.post_error[method]
        if method in self.post_status:
            if self.before_rejecting is not None:
                await self.before_rejecting()
            return httpx.Response(self.post_status[method])
        if method is not None and "id" in message:
            self.push(
                {"jsonrpc": "2.0", "id": message["id"], "result": self._result(method, message.get("params", {}))}
            )
        return httpx.Response(202)

    @staticmethod
    def _result(method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            result = InitializeResult(
                protocolVersion=params["protocolVersion"],
                capabilities=ServerCapabilities(tools=ToolsCapability()),
                serverInfo=Implementation(name=SERVER_NAME, version="1.0"),
            )
        elif method == "tools/list":
            result = ListToolsResult(tools=[Tool(name="test_tool", inputSchema={"type": "object"})])
        elif method == "tools/call":
            result = CallToolResult(content=[TextContent(type="text", text=f"Called {params['name']}")])
        else:
            result = EmptyResult()
        return result.model_dump(by_alias=True, mode="json", exclude_none=True)


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [302, 401, 429, 500, 503])
async def test_sse_client_initialize_post_http_error_fails_initialize_promptly(status_code: int) -> None:
    """A non-2xx on the initialize POST fails initialize at once instead of after the session
    read timeout (#2110: the status error was only logged, so the caller waited out the timeout)."""
    server = _RejectingSseServer()
    server.post_status["initialize"] = status_code
    with anyio.fail_after(5):
        async with (
            server,
            sse_client("http://test/sse", httpx_client_factory=server.client_factory) as streams,
            ClientSession(*streams, read_timeout_seconds=timedelta(seconds=20)) as session,
        ):
            with pytest.raises(McpError) as exc_info:
                await session.initialize()
            assert exc_info.value.error == snapshot(ErrorData(code=-32603, message="Server returned an error response"))


@pytest.mark.anyio
async def test_sse_client_request_post_http_error_fails_request_and_session_survives() -> None:
    """A non-2xx on a later request's POST fails that request at once, and the writer keeps
    sending: the next requests in the same session still reach the server (#2110)."""
    server = _RejectingSseServer()
    with anyio.fail_after(5):
        async with (
            server,
            sse_client("http://test/sse", httpx_client_factory=server.client_factory) as streams,
            ClientSession(*streams, read_timeout_seconds=timedelta(seconds=20)) as session,
        ):
            await session.initialize()
            server.post_status["tools/call"] = 500

            with pytest.raises(McpError) as exc_info:
                await session.call_tool("test_tool", {})
            assert exc_info.value.error.code == types.INTERNAL_ERROR

            assert isinstance(await session.send_ping(), EmptyResult)
            server.post_status.clear()
            result = await session.call_tool("test_tool", {})
            assert result.content == [TextContent(type="text", text="Called test_tool")]


@pytest.mark.anyio
async def test_sse_client_request_post_network_error_fails_request_and_session_survives() -> None:
    """A POST that raises before any response fails its request with CONNECTION_CLOSED, and the
    writer keeps sending (#2110)."""
    server = _RejectingSseServer()
    with anyio.fail_after(5):
        async with (
            server,
            sse_client("http://test/sse", httpx_client_factory=server.client_factory) as streams,
            ClientSession(*streams, read_timeout_seconds=timedelta(seconds=20)) as session,
        ):
            await session.initialize()
            server.post_error["tools/call"] = httpx.ConnectError("connection refused")

            with pytest.raises(McpError) as exc_info:
                await session.call_tool("test_tool", {})
            assert exc_info.value.error == snapshot(
                ErrorData(code=-32000, message="Failed to send message: connection refused")
            )

            assert isinstance(await session.send_ping(), EmptyResult)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("/messages/?session_id=abc123", ErrorData(code=-32600, message="Session terminated")),
        ("/messages/", ErrorData(code=-32603, message="Server returned an error response")),
    ],
)
async def test_sse_client_request_post_404_reports_session_terminated_only_with_a_session(
    endpoint: str, expected: ErrorData
) -> None:
    """A 404 on a POST to an endpoint that carries a session id means the session is gone, as in
    the streamable HTTP transport; without a session id it is a generic error."""
    server = _RejectingSseServer(endpoint=endpoint)
    with anyio.fail_after(5):
        async with (
            server,
            sse_client("http://test/sse", httpx_client_factory=server.client_factory) as streams,
            ClientSession(*streams) as session,
        ):
            await session.initialize()
            server.post_status["tools/call"] = 404
            with pytest.raises(McpError) as exc_info:
                await session.call_tool("test_tool", {})
            assert exc_info.value.error == expected


@pytest.mark.anyio
async def test_sse_client_notification_post_error_leaves_session_usable() -> None:
    """A failed notification POST has no waiting caller, so it is only logged and the session
    keeps working."""
    server = _RejectingSseServer()
    server.post_status["notifications/initialized"] = 500
    with anyio.fail_after(5):
        async with (
            server,
            sse_client("http://test/sse", httpx_client_factory=server.client_factory) as streams,
            ClientSession(*streams) as session,
        ):
            await session.initialize()
            assert isinstance(await session.send_ping(), EmptyResult)


@pytest.mark.anyio
async def test_sse_client_failed_post_while_answering_a_server_request_does_not_deadlock() -> None:
    """The session answers server requests inside its receive loop, so its reply can be waiting on
    the writer while a POST fails. Both must still complete: the failed request gets its error and
    the reply reaches the server."""
    server = _RejectingSseServer()
    roots_requested = anyio.Event()

    async def list_roots(context: RequestContext[ClientSession, Any]) -> ListRootsResult:
        roots_requested.set()
        return ListRootsResult(roots=[])

    async def ask_for_roots_first() -> None:
        server.push({"jsonrpc": "2.0", "id": "srv-1", "method": "roots/list"})
        await roots_requested.wait()

    server.before_rejecting = ask_for_roots_first
    with anyio.fail_after(5):
        async with (
            server,
            sse_client("http://test/sse", httpx_client_factory=server.client_factory) as streams,
            ClientSession(*streams, list_roots_callback=list_roots) as session,
        ):
            await session.initialize()
            server.post_status["tools/call"] = 500
            with pytest.raises(McpError):
                await session.call_tool("test_tool", {})
            assert isinstance(await session.send_ping(), EmptyResult)


@pytest.mark.anyio
async def test_sse_client_post_error_after_reader_closed_is_contained() -> None:
    """A failed POST whose error can no longer be delivered, because the read stream already
    closed, is contained: the writer keeps sending."""
    posted: list[str] = []
    second_post = anyio.Event()

    async def serve(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, text="event: endpoint\ndata: /messages/\n\n"
            )
        posted.append(json.loads(request.content)["method"])
        if len(posted) == 2:
            second_post.set()
        return httpx.Response(500)

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(serve))

    with anyio.fail_after(5):
        async with sse_client("http://test/sse", httpx_client_factory=factory) as (read_stream, write_stream):
            with pytest.raises(anyio.EndOfStream):
                await read_stream.receive()
            for request_id, method in [(1, "first/call"), (2, "second/call")]:
                request = types.JSONRPCRequest(jsonrpc="2.0", id=request_id, method=method, params={})
                await write_stream.send(SessionMessage(types.JSONRPCMessage(request)))
            await second_post.wait()
    assert posted == ["first/call", "second/call"]
