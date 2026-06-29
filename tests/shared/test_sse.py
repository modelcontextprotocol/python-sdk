"""Tests for the SSE client and server transports, driven entirely in process."""

import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from urllib.parse import urlparse

import anyio
import httpx
import mcp_types as types
import pytest
from httpx_sse import ServerSentEvent
from inline_snapshot import snapshot
from mcp_types import (
    CallToolRequestParams,
    CallToolResult,
    EmptyResult,
    Implementation,
    InitializeResult,
    JSONRPCResponse,
    ListToolsResult,
    PaginatedRequestParams,
    ReadResourceRequestParams,
    ReadResourceResult,
    ServerCapabilities,
    TextContent,
    TextResourceContents,
    Tool,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

import mcp.client.sse
from mcp.client.session import ClientSession
from mcp.client.sse import _extract_session_id_from_endpoint, sse_client
from mcp.server import Server, ServerRequestContext
from mcp.server.sse import SseServerTransport
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared._httpx_utils import McpHttpClientFactory
from mcp.shared.exceptions import MCPError
from tests.interaction.transports import StreamingASGITransport

SERVER_NAME = "test_server_for_SSE"

# The in-process app is mounted at this origin purely so URLs are well-formed; nothing listens here.
BASE_URL = "http://127.0.0.1:8000"


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


async def _handle_read_resource(ctx: ServerRequestContext, params: ReadResourceRequestParams) -> ReadResourceResult:
    uri = str(params.uri)
    parsed = urlparse(uri)
    if parsed.scheme == "foobar":
        return ReadResourceResult(
            contents=[TextResourceContents(uri=uri, text=f"Read {parsed.netloc}", mime_type="text/plain")]
        )
    raise MCPError(code=404, message="OOPS! no resource with that URI was found")


def make_app(server: Server) -> Starlette:
    """Mount `server` on a Starlette app exposing the SSE transport at /sse and /messages/."""
    # DNS-rebinding protection guards against an attack that cannot exist in-process; the
    # behaviour itself is pinned by tests/server/test_sse_security.py.
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
    return make_app(Server(SERVER_NAME, on_read_resource=_handle_read_resource))


@pytest.mark.anyio
async def test_raw_sse_connection() -> None:
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
    factory = in_process_client_factory(make_server_app())
    async with sse_client(f"{BASE_URL}/sse", httpx_client_factory=factory) as streams:
        async with ClientSession(*streams) as session:
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.server_info.name == SERVER_NAME

            ping_result = await session.send_ping()
            assert isinstance(ping_result, EmptyResult)


@pytest.mark.anyio
async def test_sse_client_on_session_created() -> None:
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
    assert _extract_session_id_from_endpoint(endpoint_url) == expected


@pytest.mark.anyio
async def test_sse_client_on_session_created_not_called_when_no_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = in_process_client_factory(make_server_app())
    callback_mock = Mock()

    def mock_extract(url: str) -> None:
        return None

    monkeypatch.setattr(mcp.client.sse, "_extract_session_id_from_endpoint", mock_extract)

    async with sse_client(f"{BASE_URL}/sse", httpx_client_factory=factory, on_session_created=callback_mock) as streams:
        async with ClientSession(*streams) as session:
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            # The endpoint event arrives before sse_client yields, so the callback would have fired by now.
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
    session = initialized_sse_client_session
    response = await session.read_resource(uri="foobar://should-work")
    assert len(response.contents) == 1
    assert isinstance(response.contents[0], TextResourceContents)
    assert response.contents[0].text == "Read should-work"


@pytest.mark.anyio
async def test_sse_client_exception_handling(
    initialized_sse_client_session: ClientSession,
) -> None:
    session = initialized_sse_client_session
    with pytest.raises(MCPError, match="OOPS! no resource with that URI was found"):
        await session.read_resource(uri="xxx://will-not-work")


@pytest.mark.anyio
async def test_sse_client_basic_connection_mounted_app() -> None:
    main_app = Starlette(routes=[Mount("/mounted_app", app=make_server_app())])
    factory = in_process_client_factory(main_app)

    async with sse_client(f"{BASE_URL}/mounted_app/sse", httpx_client_factory=factory) as streams:
        async with ClientSession(*streams) as session:
            result = await session.initialize()
            assert isinstance(result, InitializeResult)
            assert result.server_info.name == SERVER_NAME

            ping_result = await session.send_ping()
            assert isinstance(ping_result, EmptyResult)


async def _handle_context_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    assert params.name in ("echo_headers", "echo_context")
    assert ctx.request is not None
    headers_info = dict(ctx.request.headers)

    if params.name == "echo_headers":
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(headers_info))])

    assert params.arguments is not None
    context_data = {
        "request_id": params.arguments.get("request_id"),
        "headers": headers_info,
    }
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(context_data))])


async def _handle_context_list_tools(
    ctx: ServerRequestContext, params: PaginatedRequestParams | None
) -> ListToolsResult:
    return ListToolsResult(
        tools=[
            Tool(
                name="echo_headers",
                description="Echoes request headers",
                input_schema={"type": "object", "properties": {}},
            ),
            Tool(
                name="echo_context",
                description="Echoes request context",
                input_schema={
                    "type": "object",
                    "properties": {"request_id": {"type": "string"}},
                    "required": ["request_id"],
                },
            ),
        ]
    )


def make_context_server_app() -> Starlette:
    return make_app(
        Server(
            "request_context_server",
            on_call_tool=_handle_context_call_tool,
            on_list_tools=_handle_context_list_tools,
        )
    )


@pytest.mark.anyio
async def test_request_context_propagation() -> None:
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
    factory = in_process_client_factory(make_context_server_app())
    contexts: list[dict[str, Any]] = []

    for i in range(3):
        headers = {"X-Request-Id": f"request-{i}", "X-Custom-Value": f"value-{i}"}

        async with sse_client(f"{BASE_URL}/sse", httpx_client_factory=factory, headers=headers) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()

                tool_result = await session.call_tool("echo_context", {"request_id": f"request-{i}"})

                assert len(tool_result.content) == 1
                content = tool_result.content[0]
                assert isinstance(content, TextContent)
                contexts.append(json.loads(content.text))

    assert len(contexts) == 3
    for i, ctx in enumerate(contexts):
        assert ctx["request_id"] == f"request-{i}"
        assert ctx["headers"].get("x-request-id") == f"request-{i}"
        assert ctx["headers"].get("x-custom-value") == f"value-{i}"


def test_sse_message_id_coercion() -> None:
    """A string id that looks like an integer must not be coerced to one.

    JSON-RPC 2.0 requires the response id to match the request id's type
    (https://www.jsonrpc.org/specification#response_object). Regression test for
    https://github.com/modelcontextprotocol/python-sdk/pull/851.
    """
    json_message = '{"jsonrpc": "2.0", "id": "123", "method": "ping", "params": null}'
    msg = types.JSONRPCRequest.model_validate_json(json_message)
    assert msg == snapshot(types.JSONRPCRequest(method="ping", jsonrpc="2.0", id="123"))

    json_message = '{"jsonrpc": "2.0", "id": 123, "method": "ping", "params": null}'
    msg = types.JSONRPCRequest.model_validate_json(json_message)
    assert msg == snapshot(types.JSONRPCRequest(method="ping", jsonrpc="2.0", id=123))


@pytest.mark.parametrize(
    "endpoint, expected_result",
    [
        ("/messages/", "/messages/"),
        ("messages/", "/messages/"),
        ("/", "/"),
        ("http://example.com/messages/", ValueError),
        ("//example.com/messages/", ValueError),
        ("ftp://example.com/messages/", ValueError),
        ("/messages/?param=value", ValueError),
        ("/messages/#fragment", ValueError),
    ],
)
def test_sse_server_transport_endpoint_validation(endpoint: str, expected_result: str | type[Exception]) -> None:
    if isinstance(expected_result, type):
        with pytest.raises(expected_result, match="is not a relative path.*expecting a relative path"):
            SseServerTransport(endpoint)
    else:
        sse = SseServerTransport(endpoint)
        assert sse._endpoint == expected_result
        assert sse._endpoint.startswith("/")


@pytest.mark.anyio
async def test_sse_client_handles_empty_keepalive_pings() -> None:
    """Empty-data SSE events (keep-alive pings) are skipped without crashing.

    The MCP spec (Streamable HTTP transport) says servers SHOULD send an event with an empty
    data field to prime the client to reconnect, so the reader must tolerate them.
    """
    init_result = InitializeResult(
        protocol_version="2024-11-05",
        capabilities=ServerCapabilities(),
        server_info=Implementation(name="test", version="1.0"),
    )
    response = JSONRPCResponse(
        jsonrpc="2.0",
        id=1,
        result=init_result.model_dump(by_alias=True, exclude_none=True),
    )
    response_json = response.model_dump_json(by_alias=True, exclude_none=True)

    async def mock_aiter_sse() -> AsyncGenerator[ServerSentEvent, None]:
        yield ServerSentEvent(event="endpoint", data="/messages/?session_id=abc123")
        # The empty-data keep-alive ping under test
        yield ServerSentEvent(event="message", data="")
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
            # The empty event is skipped; the first received message is the real response.
            msg = await read_stream.receive()
            assert not isinstance(msg, Exception)
            assert isinstance(msg.message, types.JSONRPCResponse)
            assert msg.message.id == 1


@pytest.mark.anyio
async def test_sse_session_cleanup_on_disconnect() -> None:
    """Regression test for https://github.com/modelcontextprotocol/python-sdk/issues/1227.

    Disconnect must remove the session from _read_stream_writers; otherwise stale sessions
    accumulate and POSTs to them return 202 Accepted, then ClosedResourceError on write.
    """
    factory = in_process_client_factory(make_server_app())
    captured: list[str] = []

    async with sse_client(
        f"{BASE_URL}/sse", httpx_client_factory=factory, on_session_created=captured.append
    ) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()

    async with factory() as client:
        response = await client.post(
            f"/messages/?session_id={captured[0]}",
            json={"jsonrpc": "2.0", "method": "ping", "id": 99},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 404
