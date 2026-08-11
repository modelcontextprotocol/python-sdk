"""Tests for the SSE client and server transports, driven entirely in process."""

import json
from collections.abc import AsyncGenerator, Callable
from types import TracebackType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock
from urllib.parse import urlparse

import anyio
import httpx2
import mcp_types as types
import pytest
from httpx2 import ServerSentEvent
from inline_snapshot import snapshot
from mcp_types import (
    CallToolRequestParams,
    CallToolResult,
    EmptyResult,
    Implementation,
    InitializeResult,
    JSONRPCRequest,
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
from starlette.responses import Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

import mcp.client.sse
from mcp.client.auth.exceptions import OAuthTokenError
from mcp.client.session import ClientSession
from mcp.client.sse import _extract_session_id_from_endpoint, sse_client
from mcp.server import Server, ServerRequestContext
from mcp.server.sse import SseServerTransport
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared._httpx_utils import McpHttpClientFactory
from mcp.shared.exceptions import MCPError
from mcp.shared.message import SessionMessage
from tests.interaction.transports import StreamingASGITransport

SERVER_NAME = "test_server_for_SSE"

# The in-process app is mounted at this origin purely so URLs are well-formed; nothing listens here.
BASE_URL = "http://127.0.0.1:8000"


def in_process_client_factory(app: Starlette) -> McpHttpClientFactory:
    """An httpx_client_factory for sse_client whose clients are served in process by `app`."""

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
    ) -> httpx2.AsyncClient:
        # The SSE GET runs until it observes a disconnect, so the bridge must let the
        # application drain on close rather than cancelling it. follow_redirects matches
        # create_mcp_http_client, the factory this one stands in for.
        return httpx2.AsyncClient(
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


def make_app(server: Server, wrap_post: Callable[[ASGIApp], ASGIApp] | None = None) -> Starlette:
    """Mount `server` on a Starlette app exposing the SSE transport at /sse and /messages/.

    `wrap_post` optionally wraps the message-POST ASGI app (e.g. to inject HTTP failures).
    """
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

    post_app: ASGIApp = sse.handle_post_message
    if wrap_post is not None:
        post_app = wrap_post(post_app)

    return Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=post_app),
        ]
    )


def make_server_app() -> Starlette:
    return make_app(Server(SERVER_NAME, on_read_resource=_handle_read_resource))


def make_app_rejecting_posts(reject: dict[str, int]) -> Starlette:
    """Like `make_server_app`, but the message POST is answered with a bare HTTP error
    for JSON-RPC messages whose method appears in `reject` (they never reach the server)."""

    def wrap(inner: ASGIApp) -> ASGIApp:
        async def handle_post(scope: Scope, receive: Receive, send: Send) -> None:
            body = await Request(scope, receive).body()
            status = reject.get(json.loads(body).get("method"))
            if status is not None:
                await Response(status_code=status)(scope, receive, send)
                return

            async def replay() -> dict[str, Any]:
                return {"type": "http.request", "body": body, "more_body": False}

            await inner(scope, replay, send)

        return handle_post

    return make_app(Server(SERVER_NAME, on_read_resource=_handle_read_resource), wrap_post=wrap)


@pytest.mark.anyio
async def test_raw_sse_connection() -> None:
    """The SSE GET responds 200 with an event-stream content type, announcing the session
    endpoint as its first event."""
    http_client = httpx2.AsyncClient(
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
            assert result.server_info.name == SERVER_NAME

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
    response = await session.read_resource(uri="foobar://should-work")
    assert len(response.contents) == 1
    assert isinstance(response.contents[0], TextResourceContents)
    assert response.contents[0].text == "Read should-work"


@pytest.mark.anyio
async def test_sse_client_exception_handling(
    initialized_sse_client_session: ClientSession,
) -> None:
    """A server-side MCPError reaches the client with its message intact."""
    session = initialized_sse_client_session
    with pytest.raises(MCPError, match="OOPS! no resource with that URI was found"):
        await session.read_resource(uri="xxx://will-not-work")


@pytest.mark.anyio
@pytest.mark.parametrize("status_code", [302, 401, 403, 500])
async def test_sse_client_request_post_http_error_reaches_caller_and_session_survives(status_code: int) -> None:
    """A non-2xx on a request's message POST reaches the waiting caller promptly as a JSON-RPC
    error correlated to the request, and the session stays usable (SDK-defined; #2110 — the
    status error used to be swallowed inside post_writer, hanging the caller forever).
    An unfollowed redirect counts: the message never reached the server, so no response can arrive.
    """
    factory = in_process_client_factory(make_app_rejecting_posts({"resources/read": status_code}))
    with anyio.fail_after(5):
        # One parenthesized async-with: separately nested ones trip a phantom
        # branch arc under coverage on Python 3.14 (see the note in mcp.client.sse).
        async with (
            sse_client(f"{BASE_URL}/sse", httpx_client_factory=factory) as streams,
            ClientSession(*streams) as session,
        ):
            await session.initialize()

            with pytest.raises(MCPError) as exc_info:
                await session.read_resource(uri="foobar://should-work")
            assert exc_info.value.error.code == types.INTERNAL_ERROR
            assert exc_info.value.error.message == snapshot("Server returned an error response")

            # The session survived the failed POST: the next request round-trips.
            assert isinstance(await session.send_ping(), EmptyResult)


@pytest.mark.anyio
async def test_sse_client_request_post_network_error_reaches_caller_and_session_survives() -> None:
    """A network-level failure on a request's message POST reaches the waiting caller promptly
    as a JSON-RPC error correlated to the request, and the session stays usable (SDK-defined;
    #2110 — the exception used to be swallowed inside post_writer, hanging the caller forever).
    """

    class _FlakyPostTransport(httpx2.AsyncBaseTransport):
        """Serves the standard test app, but the POST of one JSON-RPC method never connects."""

        def __init__(self) -> None:
            self._inner = StreamingASGITransport(make_server_app(), cancel_on_close=False)

        async def __aenter__(self) -> "_FlakyPostTransport":
            await self._inner.__aenter__()
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None = None,
            exc_value: BaseException | None = None,
            traceback: TracebackType | None = None,
        ) -> None:
            await self._inner.__aexit__(exc_type, exc_value, traceback)

        async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
            if request.method == "POST" and json.loads(request.content).get("method") == "resources/read":
                raise httpx2.ConnectError("connection refused", request=request)
            return await self._inner.handle_async_request(request)

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
    ) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=_FlakyPostTransport(), base_url=BASE_URL, headers=headers, timeout=timeout, auth=auth
        )

    with anyio.fail_after(5):
        # One parenthesized async-with: separately nested ones trip a phantom
        # branch arc under coverage on Python 3.14 (see the note in mcp.client.sse).
        async with (
            sse_client(f"{BASE_URL}/sse", httpx_client_factory=factory) as streams,
            ClientSession(*streams) as session,
        ):
            await session.initialize()

            with pytest.raises(MCPError) as exc_info:
                await session.read_resource(uri="foobar://should-work")
            assert exc_info.value.error.code == types.CONNECTION_CLOSED
            # The message embeds httpx's exception text; pin only the SDK-authored prefix.
            assert exc_info.value.error.message.startswith("Failed to send message:")

            # The session survived the failed POST: the next request round-trips.
            assert isinstance(await session.send_ping(), EmptyResult)


@pytest.mark.anyio
async def test_sse_client_post_404_with_session_endpoint_reports_session_terminated() -> None:
    """A 404 on a request's message POST while the endpoint URL carries a session id reports
    "Session terminated" (INVALID_REQUEST) to the caller, the same session-expiry mapping as
    the streamable HTTP transport (SDK-defined)."""
    factory = in_process_client_factory(make_app_rejecting_posts({"resources/read": 404}))
    with anyio.fail_after(5):
        # One parenthesized async-with: separately nested ones trip a phantom
        # branch arc under coverage on Python 3.14 (see the note in mcp.client.sse).
        async with (
            sse_client(f"{BASE_URL}/sse", httpx_client_factory=factory) as streams,
            ClientSession(*streams) as session,
        ):
            await session.initialize()

            with pytest.raises(MCPError) as exc_info:
                await session.read_resource(uri="foobar://should-work")
            assert exc_info.value.error.code == types.INVALID_REQUEST
            assert exc_info.value.error.message == snapshot("Session terminated")


@pytest.mark.anyio
async def test_sse_client_post_404_without_session_endpoint_keeps_generic_error() -> None:
    """A 404 on a request's message POST when the endpoint URL carries no session id keeps the
    generic error: with no session to expire, "Session terminated" would be a lie (SDK-defined).
    The raw endpoint is scripted because `SseServerTransport` always issues a session id."""

    async def handle_sse(request: Request) -> StreamingResponse:
        async def stream() -> AsyncGenerator[str, None]:
            yield "event: endpoint\ndata: /messages/\n\n"
            await anyio.Event().wait()  # park until the client disconnects

        return StreamingResponse(stream(), media_type="text/event-stream")

    async def handle_post(request: Request) -> Response:
        return Response(status_code=404)

    app = Starlette(routes=[Route("/sse", handle_sse), Route("/messages/", handle_post, methods=["POST"])])
    factory = in_process_client_factory(app)
    with anyio.fail_after(5):
        async with (
            sse_client(f"{BASE_URL}/sse", httpx_client_factory=factory) as streams,
            ClientSession(*streams) as session,
        ):
            with pytest.raises(MCPError) as exc_info:
                await session.initialize()
            assert exc_info.value.error.code == types.INTERNAL_ERROR
            assert exc_info.value.error.message == snapshot("Server returned an error response")


@pytest.mark.anyio
@pytest.mark.parametrize("exc_type", [OAuthTokenError, RuntimeError])
async def test_sse_client_auth_failure_on_post_reaches_caller_and_session_survives(
    exc_type: type[Exception],
) -> None:
    """A failure raised from inside a request's message POST by a user-supplied hook — an SDK
    OAuth flow error, or any exception from a custom auth flow — reaches the waiting caller
    promptly as a JSON-RPC error correlated to the request, and the session stays usable
    (SDK-defined; #2110 — like any network error, it used to be swallowed inside post_writer)."""

    class _RefusingAuth(httpx2.Auth):
        """Stands in for OAuthClientProvider (or any user auth hook) failing mid-session."""

        async def async_auth_flow(self, request: httpx2.Request) -> AsyncGenerator[httpx2.Request, httpx2.Response]:
            if request.method == "POST" and json.loads(request.content).get("method") == "resources/read":
                raise exc_type("re-authentication failed")
            yield request

    factory = in_process_client_factory(make_server_app())
    with anyio.fail_after(5):
        async with (
            sse_client(f"{BASE_URL}/sse", httpx_client_factory=factory, auth=_RefusingAuth()) as streams,
            ClientSession(*streams) as session,
        ):
            await session.initialize()

            with pytest.raises(MCPError) as exc_info:
                await session.read_resource(uri="foobar://should-work")
            assert exc_info.value.error.code == types.CONNECTION_CLOSED
            # The message embeds the auth exception's text; pin only the SDK-authored prefix.
            assert exc_info.value.error.message.startswith("Failed to send message:")

            # The session survived the failed POST: the next request round-trips.
            assert isinstance(await session.send_ping(), EmptyResult)


@pytest.mark.anyio
async def test_sse_client_post_error_after_reader_closed_is_contained() -> None:
    """A failing POST whose error can no longer be delivered — the read stream already closed
    with the server's SSE stream — is contained: the write loop survives and later messages
    still reach the server (SDK-defined teardown-race guard). Raw streams, because the race
    needs the read side closed while the write side keeps sending."""
    posted: list[str] = []
    second_post = anyio.Event()

    async def handle_sse(request: Request) -> StreamingResponse:
        async def stream() -> AsyncGenerator[str, None]:
            # The stream ends right after the endpoint event: the client's reader
            # observes EOF and closes the read stream.
            yield "event: endpoint\ndata: /messages/\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    async def handle_post(request: Request) -> Response:
        posted.append(json.loads(await request.body())["method"])
        if len(posted) == 2:
            second_post.set()
        return Response(status_code=500)

    app = Starlette(routes=[Route("/sse", handle_sse), Route("/messages/", handle_post, methods=["POST"])])
    factory = in_process_client_factory(app)
    with anyio.fail_after(5):
        async with sse_client(f"{BASE_URL}/sse", httpx_client_factory=factory) as (read, write):
            # Wait for the reader to observe the server's EOF and close the read stream.
            with pytest.raises(anyio.EndOfStream):
                await read.receive()

            await write.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=1, method="first/call", params={})))
            await write.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=2, method="second/call", params={})))
            await second_post.wait()
    # The first POST's undeliverable error was contained; the second still went out.
    assert posted == ["first/call", "second/call"]


@pytest.mark.anyio
async def test_sse_client_notification_post_http_error_leaves_session_usable() -> None:
    """A non-2xx on a notification's message POST resolves no caller (a notification has no
    waiter) and leaves the session usable for subsequent requests (SDK-defined; #2110)."""
    factory = in_process_client_factory(make_app_rejecting_posts({"notifications/cancelled": 500}))
    with anyio.fail_after(5):
        # One parenthesized async-with: separately nested ones trip a phantom
        # branch arc under coverage on Python 3.14 (see the note in mcp.client.sse).
        async with (
            sse_client(f"{BASE_URL}/sse", httpx_client_factory=factory) as streams,
            ClientSession(*streams) as session,
        ):
            await session.initialize()

            # Fire-and-forget: the rejected POST must neither raise nor stall the writer.
            await session.send_notification(
                types.CancelledNotification(params=types.CancelledNotificationParams(request_id=999))
            )

            # The write loop is serialized, so this request's POST happens strictly after
            # the rejected one; its success proves the failure was contained.
            assert isinstance(await session.send_ping(), EmptyResult)


@pytest.mark.anyio
async def test_sse_client_basic_connection_mounted_app() -> None:
    """The SSE transport works unchanged when its app is mounted under a sub-path."""
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
    """Custom HTTP headers on the SSE connection are visible to server handlers via ctx.request."""
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
    contexts: list[dict[str, Any]] = []

    # Connect three clients in turn, each with its own headers.
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
    """Previously, the `RequestId` would coerce a string that looked like an integer into an integer.

    See <https://github.com/modelcontextprotocol/python-sdk/pull/851> for more details.

    As per the JSON-RPC 2.0 specification, the id in the response object needs to be the same type as the id in the
    request object. In other words, we can't perform the coercion.

    See <https://www.jsonrpc.org/specification#response_object> for more details.
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

    # Mock SSE events using httpx2's ServerSentEvent: an endpoint event, an
    # empty keep-alive ping (the case under test), then a real response.
    mock_event_source = MagicMock()
    mock_event_source.__aiter__.return_value = [
        ServerSentEvent(event="endpoint", data="/messages/?session_id=abc123"),
        ServerSentEvent(event="message", data=""),
        ServerSentEvent(event="message", data=response_json),
    ]
    mock_event_source.response.raise_for_status = MagicMock()

    mock_sse = MagicMock()
    mock_sse.__aenter__ = AsyncMock(return_value=mock_event_source)
    mock_sse.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.sse = MagicMock(return_value=mock_sse)
    mock_client.post = AsyncMock(return_value=MagicMock(status_code=200, raise_for_status=MagicMock()))

    def mock_factory(
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
    ) -> httpx2.AsyncClient:
        return mock_client

    async with sse_client("http://test/sse", httpx_client_factory=mock_factory) as (read_stream, _):
        # Read the message - should skip the empty one and get the real response
        msg = await read_stream.receive()
        # If we get here without error, the empty message was skipped successfully
        assert not isinstance(msg, Exception)
        assert isinstance(msg.message, types.JSONRPCResponse)
        assert msg.message.id == 1


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
