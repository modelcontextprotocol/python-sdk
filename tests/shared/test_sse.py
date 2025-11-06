import json
from collections.abc import AsyncGenerator
from typing import Any

import anyio
import httpx
import pytest
from anyio.abc import TaskGroup
from inline_snapshot import snapshot
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.streaming_asgi_transport import StreamingASGITransport
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared._httpx_utils import McpHttpClientFactory
from mcp.shared.exceptions import McpError
from mcp.types import (
    EmptyResult,
    ErrorData,
    InitializeResult,
    ReadResourceResult,
    TextContent,
    TextResourceContents,
    Tool,
)

SERVER_NAME = "test_server_for_SSE"
TEST_SERVER_HOST = "testserver"
TEST_SERVER_BASE_URL = f"http://{TEST_SERVER_HOST}"


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


def create_asgi_client_factory(app: Starlette, tg: TaskGroup) -> McpHttpClientFactory:
    """Factory function to create httpx clients with StreamingASGITransport"""

    def asgi_client_factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        transport = StreamingASGITransport(app=app, task_group=tg)
        return httpx.AsyncClient(
            transport=transport, base_url=TEST_SERVER_BASE_URL, headers=headers, timeout=timeout, auth=auth
        )

    return asgi_client_factory


def create_sse_app(server: Server) -> Starlette:
    """Helper to create SSE app with given server"""
    security_settings = TransportSecuritySettings(
        allowed_hosts=[TEST_SERVER_HOST],
        allowed_origins=[TEST_SERVER_BASE_URL],
    )
    sse = SseServerTransport("/messages/", security_settings=security_settings)

    async def handle_sse(request: Request) -> Response:
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())
        return Response()

    return Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )


# Test fixtures


@pytest.fixture()
def server_app() -> Starlette:
    """Create test Starlette app with SSE transport"""
    app = create_sse_app(ServerTest())
    return app


@pytest.fixture()
async def tg() -> AsyncGenerator[TaskGroup, None]:
    async with anyio.create_task_group() as tg:
        try:
            yield tg
        finally:
            tg.cancel_scope.cancel()


@pytest.fixture()
async def http_client(tg: TaskGroup, server_app: Starlette) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create test client using StreamingASGITransport"""
    transport = StreamingASGITransport(app=server_app, task_group=tg)
    async with httpx.AsyncClient(transport=transport, base_url=TEST_SERVER_BASE_URL) as client:
        yield client


@pytest.fixture()
async def sse_client_session(tg: TaskGroup, server_app: Starlette) -> AsyncGenerator[ClientSession, None]:
    asgi_client_factory = create_asgi_client_factory(server_app, tg)

    async with sse_client(
        f"{TEST_SERVER_BASE_URL}/sse",
        httpx_client_factory=asgi_client_factory,
    ) as streams:
        async with ClientSession(*streams) as session:
            yield session


# Tests
@pytest.mark.anyio
async def test_raw_sse_connection(http_client: httpx.AsyncClient) -> None:
    """Test the SSE connection establishment simply with an HTTP client."""

    async def connection_test() -> None:
        async with http_client.stream("GET", "/sse") as response:
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            line_number = 0
            async for line in response.aiter_lines():
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
async def test_sse_client_basic_connection(sse_client_session: ClientSession) -> None:
    # Test initialization
    result = await sse_client_session.initialize()
    assert isinstance(result, InitializeResult)
    assert result.serverInfo.name == SERVER_NAME

    # Test ping
    ping_result = await sse_client_session.send_ping()
    assert isinstance(ping_result, EmptyResult)


@pytest.fixture
async def initialized_sse_client_session(sse_client_session: ClientSession) -> AsyncGenerator[ClientSession, None]:
    session = sse_client_session
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
async def test_sse_client_timeout(
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


@pytest.fixture()
async def mounted_server_app(server_app: Starlette) -> Starlette:
    """Create a mounted server app"""
    app = Starlette(routes=[Mount("/mounted_app", app=server_app)])
    return app


@pytest.fixture()
async def sse_client_mounted_server_app_session(
    tg: TaskGroup, mounted_server_app: Starlette
) -> AsyncGenerator[ClientSession, None]:
    asgi_client_factory = create_asgi_client_factory(mounted_server_app, tg)

    async with sse_client(
        f"{TEST_SERVER_BASE_URL}/mounted_app/sse",
        sse_read_timeout=0.5,
        httpx_client_factory=asgi_client_factory,
    ) as streams:
        async with ClientSession(*streams) as session:
            yield session


@pytest.mark.anyio
async def test_sse_client_basic_connection_mounted_app(sse_client_mounted_server_app_session: ClientSession) -> None:
    session = sse_client_mounted_server_app_session
    # Test initialization
    result = await session.initialize()
    assert isinstance(result, InitializeResult)
    assert result.serverInfo.name == SERVER_NAME

    # Test ping
    ping_result = await session.send_ping()
    assert isinstance(ping_result, EmptyResult)


# Test server with request context that returns headers in the response
class RequestContextServer(Server[object, Request]):
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


@pytest.fixture()
async def context_server_app() -> Starlette:
    """Fixture that provides the context server app"""
    app = create_sse_app(RequestContextServer())
    return app


@pytest.mark.anyio
async def test_request_context_propagation(tg: TaskGroup, context_server_app: Starlette) -> None:
    """Test that request context is properly propagated through SSE transport."""
    # Test with custom headers
    custom_headers = {
        "Authorization": "Bearer test-token",
        "X-Custom-Header": "test-value",
        "X-Trace-Id": "trace-123",
    }

    asgi_client_factory = create_asgi_client_factory(context_server_app, tg)

    async with sse_client(
        f"{TEST_SERVER_BASE_URL}/sse",
        headers=custom_headers,
        httpx_client_factory=asgi_client_factory,
        sse_read_timeout=0.5,
    ) as streams:
        async with ClientSession(*streams) as session:
            # Initialize the session
            result = await session.initialize()
            assert isinstance(result, InitializeResult)

            # Call the tool that echoes headers back
            tool_result = await session.call_tool("echo_headers", {})

            # Parse the JSON response
            assert len(tool_result.content) == 1
            content_item = tool_result.content[0]
            headers_data = json.loads(content_item.text if content_item.type == "text" else "{}")

            # Verify headers were propagated
            assert headers_data.get("authorization") == "Bearer test-token"
            assert headers_data.get("x-custom-header") == "test-value"
            assert headers_data.get("x-trace-id") == "trace-123"


@pytest.mark.anyio
async def test_request_context_isolation(tg: TaskGroup, context_server_app: Starlette) -> None:
    """Test that request contexts are isolated between different SSE clients."""
    contexts: list[dict[str, Any]] = []

    asgi_client_factory = create_asgi_client_factory(context_server_app, tg)

    # Create multiple clients with different headers
    for i in range(3):
        headers = {"X-Request-Id": f"request-{i}", "X-Custom-Value": f"value-{i}"}

        async with sse_client(
            f"{TEST_SERVER_BASE_URL}/sse",
            headers=headers,
            httpx_client_factory=asgi_client_factory,
        ) as streams:
            async with ClientSession(*streams) as session:
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
