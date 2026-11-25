"""Tests for StreamableHTTPSessionManager."""

import json
import logging
import math
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import anyio
import httpx2
import pytest
from mcp_types import (
    INTERNAL_ERROR,
    INVALID_REQUEST,
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
)
from mcp_types.version import LATEST_HANDSHAKE_VERSION
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext, streamable_http_manager
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER, StreamableHTTPServerTransport
from mcp.server.streamable_http_manager import (
    DEFAULT_MAX_REQUEST_BODY_SIZE,
    DEFAULT_MAX_SESSIONS,
    DEFAULT_SESSION_IDLE_TIMEOUT,
    StreamableHTTPSessionManager,
)
from tests.interaction.transports import StreamingASGITransport

# The in-process app is mounted at this origin purely so URLs are well-formed; nothing listens here.
BASE_URL = "http://127.0.0.1:8000"

_JSON_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}

_INITIALIZE_BODY = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_HANDSHAKE_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }
).encode()
"""A wire-level initialize request: the only request that may open a session."""


@pytest.mark.anyio
async def test_run_can_only_be_called_once():
    """Test that run() can only be called once per instance."""
    app = Server("test-server")
    manager = StreamableHTTPSessionManager(app=app)

    # First call should succeed
    async with manager.run():
        pass

    # Second call should raise RuntimeError
    with pytest.raises(RuntimeError) as excinfo:
        async with manager.run():
            pass  # pragma: no cover

    assert "StreamableHTTPSessionManager .run() can only be called once per instance" in str(excinfo.value)


@pytest.mark.anyio
async def test_run_prevents_concurrent_calls():
    """Test that concurrent calls to run() are prevented."""
    app = Server("test-server")
    manager = StreamableHTTPSessionManager(app=app)

    errors: list[Exception] = []

    async def try_run():
        try:
            async with manager.run():
                # Simulate some work
                await anyio.sleep(0.1)
        except RuntimeError as e:
            errors.append(e)

    # Try to run concurrently
    async with anyio.create_task_group() as tg:
        tg.start_soon(try_run)
        tg.start_soon(try_run)

    # One should succeed, one should fail
    assert len(errors) == 1
    assert "StreamableHTTPSessionManager .run() can only be called once per instance" in str(errors[0])


@pytest.mark.anyio
async def test_handle_request_without_run_raises_error():
    """Test that handle_request raises error if run() hasn't been called."""
    app = Server("test-server")
    manager = StreamableHTTPSessionManager(app=app)

    # Mock ASGI parameters
    scope: Scope = {"type": "http", "method": "POST", "path": "/test", "headers": []}

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def send(message: Message):  # pragma: no cover
        pass

    # Should raise error because run() hasn't been called
    with pytest.raises(RuntimeError) as excinfo:
        await manager.handle_request(scope, receive, send)

    assert "Task group is not initialized. Make sure to use run()." in str(excinfo.value)


@pytest.mark.anyio
async def test_oversized_content_length_is_rejected_before_body_read_or_session_creation() -> None:
    """SDK-defined: an oversized declared body gets HTTP 413 before the server reads it or creates a session."""
    manager = StreamableHTTPSessionManager(app=Server("test-size-limit"), max_request_body_size=8)
    sent_messages: list[Message] = []
    receive = AsyncMock(return_value={"type": "http.request", "body": b"123456789", "more_body": False})

    async def send(message: Message) -> None:
        sent_messages.append(message)

    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"content-length", b"9")],
    }
    async with manager.run():
        await manager.handle_request(scope, receive, send)
        assert manager._server_instances == {}

    response_start = next(message for message in sent_messages if message["type"] == "http.response.start")
    assert response_start["status"] == 413
    receive.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("headers", [[], [(b"content-length", b"invalid")], [(b"content-length", b"8")]])
async def test_oversized_streamed_body_is_rejected_before_session_creation(
    headers: list[tuple[bytes, bytes]],
) -> None:
    """SDK-defined: streamed bodies enforce the limit with missing, invalid, or understated length."""
    manager = StreamableHTTPSessionManager(app=Server("test-streamed-size-limit"), max_request_body_size=8)
    sent_messages: list[Message] = []
    request_messages: Iterator[Message] = iter(
        [
            {"type": "http.request", "body": b"1234", "more_body": True},
            {"type": "http.request", "body": b"56789", "more_body": False},
        ]
    )

    async def receive() -> Message:
        return next(request_messages)

    async def send(message: Message) -> None:
        sent_messages.append(message)

    scope: Scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": headers}
    async with manager.run():
        await manager.asgi_app(scope, receive, send)
        assert manager._server_instances == {}

    response_start = next(message for message in sent_messages if message["type"] == "http.response.start")
    assert response_start["status"] == 413


def test_request_body_limit_defaults_to_four_mib() -> None:
    """SDK-defined: Streamable HTTP request bodies are limited to 4 MiB by default."""
    manager = StreamableHTTPSessionManager(app=Server("test-default-size-limit"))
    assert manager.max_request_body_size == DEFAULT_MAX_REQUEST_BODY_SIZE == 4 * 1024 * 1024


@pytest.mark.parametrize("max_request_body_size", [0, -1])
def test_request_body_limit_rejects_non_positive_values(max_request_body_size: int) -> None:
    """SDK-defined: callers cannot disable request-size protection with a non-positive value."""
    with pytest.raises(ValueError) as exc_info:
        StreamableHTTPSessionManager(app=Server("test-invalid-size-limit"), max_request_body_size=max_request_body_size)
    assert str(exc_info.value) == "max_request_body_size must be a positive number of bytes"


class TestException(Exception):
    __test__ = False  # Prevent pytest from collecting this as a test class
    pass


@pytest.fixture
async def running_manager():
    app = Server("test-cleanup-server")
    # It's important that the app instance used by the manager is the one we can patch
    manager = StreamableHTTPSessionManager(app=app)
    async with manager.run():
        # Patch app.run here if it's simpler, or patch it within the test
        yield manager, app


@pytest.mark.anyio
async def test_stateful_session_cleanup_on_graceful_exit(running_manager: tuple[StreamableHTTPSessionManager, Server]):
    manager, _app = running_manager

    # The manager's `run_server` task drives `serve_loop` directly (the manager
    # owns lifespan); patch that seam so the loop returns immediately and we
    # can observe the cleanup that follows.
    mock_serve = AsyncMock(return_value=None)

    sent_messages: list[Message] = []

    async def mock_send(message: Message):
        sent_messages.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"content-type", b"application/json")],
    }

    async def mock_receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    # Trigger session creation
    with patch("mcp.server.streamable_http_manager.serve_loop", mock_serve):
        await manager.handle_request(scope, mock_receive, mock_send)

    # Extract session ID from response headers
    session_id = None
    for msg in sent_messages:  # pragma: no branch
        if msg["type"] == "http.response.start":  # pragma: no branch
            for header_name, header_value in msg.get("headers", []):  # pragma: no branch
                if header_name.decode().lower() == MCP_SESSION_ID_HEADER.lower():
                    session_id = header_value.decode()
                    break
            if session_id:  # Break outer loop if session_id is found  # pragma: no branch
                break

    assert session_id is not None, "Session ID not found in response headers"

    mock_serve.assert_called_once()

    # At this point, mock_serve has completed, and the finally block in
    # StreamableHTTPSessionManager's run_server should have executed.

    # To ensure the task spawned by handle_request finishes and cleanup occurs:
    # Give other tasks a chance to run. This is important for the finally block.
    await anyio.sleep(0.01)

    assert session_id not in manager._server_instances, (
        "Session ID should be removed from _server_instances after graceful exit"
    )
    assert not manager._server_instances, "No sessions should be tracked after the only session exits gracefully"


@pytest.mark.anyio
async def test_stateful_session_cleanup_on_exception(running_manager: tuple[StreamableHTTPSessionManager, Server]):
    manager, _app = running_manager

    mock_serve = AsyncMock(side_effect=TestException("Simulated crash"))

    sent_messages: list[Message] = []

    async def mock_send(message: Message):
        sent_messages.append(message)
        # If an exception occurs, the transport might try to send an error response
        # For this test, we mostly care that the session is established enough
        # to get an ID
        if message["type"] == "http.response.start" and message["status"] >= 500:  # pragma: no cover
            pass  # Expected if TestException propagates that far up the transport

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"content-type", b"application/json")],
    }

    async def mock_receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    # Trigger session creation
    with patch("mcp.server.streamable_http_manager.serve_loop", mock_serve):
        await manager.handle_request(scope, mock_receive, mock_send)

    session_id = None
    for msg in sent_messages:  # pragma: no branch
        if msg["type"] == "http.response.start":  # pragma: no branch
            for header_name, header_value in msg.get("headers", []):  # pragma: no branch
                if header_name.decode().lower() == MCP_SESSION_ID_HEADER.lower():
                    session_id = header_value.decode()
                    break
            if session_id:  # Break outer loop if session_id is found  # pragma: no branch
                break

    assert session_id is not None, "Session ID not found in response headers"

    mock_serve.assert_called_once()

    # Give other tasks a chance to run to ensure the finally block executes
    await anyio.sleep(0.01)

    assert session_id not in manager._server_instances, (
        "Session ID should be removed from _server_instances after an exception"
    )
    assert not manager._server_instances, "No sessions should be tracked after the only session crashes"


@pytest.mark.anyio
async def test_stateless_requests_memory_cleanup():
    """Test that stateless requests actually clean up resources using real transports."""
    app = Server("test-stateless-real-cleanup")
    manager = StreamableHTTPSessionManager(app=app, stateless=True)

    with _created_transports() as created_transports:
        async with manager.run():
            # Send a simple request
            sent_messages: list[Message] = []

            async def mock_send(message: Message):
                sent_messages.append(message)

            scope = {
                "type": "http",
                "method": "POST",
                "path": "/mcp",
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"accept", b"application/json, text/event-stream"),
                ],
            }

            # Empty body to trigger early return
            async def mock_receive():
                return {
                    "type": "http.request",
                    "body": b"",
                    "more_body": False,
                }

            # Send a request
            await manager.handle_request(scope, mock_receive, mock_send)

            # Verify transport was created
            assert len(created_transports) == 1, "Should have created one transport"

            transport = created_transports[0]

            # The key assertion - transport should be terminated
            assert transport._terminated, "Transport should be terminated after stateless request"

            # Verify internal state is cleaned up
            assert len(transport._request_streams) == 0, "Transport should have no active request streams"


@pytest.mark.anyio
async def test_unknown_session_id_returns_404(caplog: pytest.LogCaptureFixture):
    """Test that requests with unknown session IDs return HTTP 404 per MCP spec."""
    app = Server("test-unknown-session")
    manager = StreamableHTTPSessionManager(app=app)

    async with manager.run():
        sent_messages: list[Message] = []
        response_body = b""

        async def mock_send(message: Message):
            nonlocal response_body
            sent_messages.append(message)
            if message["type"] == "http.response.body":
                response_body += message.get("body", b"")

        # Request with a non-existent session ID
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [
                (b"content-type", b"application/json"),
                (b"accept", b"application/json, text/event-stream"),
                (b"mcp-session-id", b"non-existent-session-id"),
            ],
        }

        async def mock_receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        with caplog.at_level(logging.INFO):
            await manager.handle_request(scope, mock_receive, mock_send)

        # Find the response start message
        response_start = next(
            (msg for msg in sent_messages if msg["type"] == "http.response.start"),
            None,
        )
        assert response_start is not None, "Should have sent a response"
        assert response_start["status"] == 404, "Should return HTTP 404 for unknown session ID"

        # Verify JSON-RPC error format
        error_data = json.loads(response_body)
        assert error_data["jsonrpc"] == "2.0"
        assert error_data["id"] is None
        assert error_data["error"]["code"] == INVALID_REQUEST
        assert error_data["error"]["message"] == "Session not found"
        assert "Rejected request with unknown or expired session ID: non-existent-session-id" in caplog.text


@pytest.mark.anyio
async def test_e2e_streamable_http_server_cleanup():
    host = "testserver"

    async def handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[])

    app = Server("test-server", on_list_tools=handle_list_tools)
    mcp_app = app.streamable_http_app(host=host)
    async with (
        mcp_app.router.lifespan_context(mcp_app),
        httpx2.ASGITransport(mcp_app) as transport,
        httpx2.AsyncClient(transport=transport) as http_client,
        Client(streamable_http_client(f"http://{host}/mcp", http_client=http_client), mode="legacy") as client,
    ):
        await client.list_tools()


class _IdleTimeoutObserver(logging.Handler):
    """Resolves `reaped` when the manager logs that a session's idle timeout fired."""

    def __init__(self) -> None:
        super().__init__()
        self.reaped = anyio.Event()

    def emit(self, record: logging.LogRecord) -> None:
        if "idle timeout" in record.getMessage():
            self.reaped.set()


def _observe_idle_timeout(caplog: pytest.LogCaptureFixture, request: pytest.FixtureRequest) -> _IdleTimeoutObserver:
    """Install an observer for the manager's "idle timeout" log record for the rest of the test.

    The manager pops the session synchronously after emitting that record, before its next await,
    so a waiter woken by it always finds the session gone. caplog.set_level enables INFO so the
    record is created.
    """
    observer = _IdleTimeoutObserver()
    manager_logger = logging.getLogger(streamable_http_manager.__name__)
    manager_logger.addHandler(observer)
    request.addfinalizer(lambda: manager_logger.removeHandler(observer))
    caplog.set_level(logging.INFO, logger=streamable_http_manager.__name__)
    return observer


@contextmanager
def _created_transports() -> Iterator[list[StreamableHTTPServerTransport]]:
    """Collect every transport a session manager creates while the context is open."""
    created: list[StreamableHTTPServerTransport] = []

    def create(*args: Any, **kwargs: Any) -> StreamableHTTPServerTransport:
        transport = StreamableHTTPServerTransport(*args, **kwargs)
        created.append(transport)
        return transport

    with patch.object(streamable_http_manager, "StreamableHTTPServerTransport", side_effect=create):
        yield created


@asynccontextmanager
async def _served(
    manager: StreamableHTTPSessionManager, endpoint: ASGIApp | None = None
) -> AsyncIterator[httpx2.AsyncClient]:
    """Run `manager` behind an in-process HTTP client whose responses stream as they are produced.

    `endpoint` is the ASGI app mounted for it; by default the manager itself.
    """
    app = Starlette(routes=[Mount("/", app=endpoint or manager.handle_request)])
    async with manager.run(), httpx2.AsyncClient(transport=StreamingASGITransport(app), base_url=BASE_URL) as http:
        yield http


@pytest.mark.anyio
async def test_idle_session_is_reaped(caplog: pytest.LogCaptureFixture, request: pytest.FixtureRequest):
    """After idle timeout fires, the session returns 404."""
    app = Server("test-idle-reap")
    manager = StreamableHTTPSessionManager(app=app, session_idle_timeout=0.05)
    observer = _observe_idle_timeout(caplog, request)

    async with manager.run():
        session_id = await _open_session(manager, None)

        # Wait for the 50ms idle timeout to fire and the session to be unregistered. Re-requesting
        # the session to poll for the 404 would push its idle deadline forward and keep it alive.
        with anyio.fail_after(5):
            await observer.reaped.wait()

        # Verify via public API: old session ID now returns 404
        assert await _request_session(manager, session_id, None) == 404


@pytest.mark.anyio
async def test_request_in_flight_holds_the_session_open(
    caplog: pytest.LogCaptureFixture, request: pytest.FixtureRequest
) -> None:
    """A session does not expire while one of its requests is still being served, however long that takes;
    the idle period is counted from the moment its last request completes."""
    tool_started = anyio.Event()
    release_tool = anyio.Event()

    async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        tool_started.set()
        await release_tool.wait()
        return CallToolResult(content=[TextContent(type="text", text="done")])

    app = Server("test-in-flight", on_call_tool=handle_call_tool)
    manager = StreamableHTTPSessionManager(app=app, session_idle_timeout=30)
    observer = _observe_idle_timeout(caplog, request)

    async with _served(manager) as http:
        initialize = await http.post("/mcp", content=_INITIALIZE_BODY, headers=_JSON_HEADERS)
        assert initialize.status_code == 200
        session_id = initialize.headers[MCP_SESSION_ID_HEADER]
        transport = manager._server_instances[session_id]
        session_headers = _JSON_HEADERS | {MCP_SESSION_ID_HEADER: session_id}
        call_tool_body: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "slow", "arguments": {}},
        }
        responses: list[httpx2.Response] = []

        async def call_tool() -> None:
            responses.append(await http.post("/mcp", json=call_tool_body, headers=session_headers))

        async with anyio.create_task_group() as tg:
            tg.start_soon(call_tool)
            with anyio.fail_after(5):
                await tool_started.wait()
            # While the call is being served the idle countdown is suspended.
            assert transport.idle_scope is not None and transport.idle_scope.deadline == math.inf
            # From here on a short idle period, counted from the moment the call completes.
            transport._idle_timeout = 0.05
            release_tool.set()

        assert responses[0].status_code == 200
        assert '"done"' in responses[0].text

        # Nothing is in flight any more, so the idle period now runs out.
        with anyio.fail_after(5):
            await observer.reaped.wait()
        assert session_id not in manager._server_instances
        assert transport.is_terminated
        followup = await http.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "ping"}, headers=session_headers)
        assert followup.status_code == 404


@pytest.mark.anyio
async def test_open_event_stream_holds_the_session_open(
    caplog: pytest.LogCaptureFixture, request: pytest.FixtureRequest
) -> None:
    """A client listening on the session's GET stream keeps the session, even if it sends nothing;
    once the stream closes the idle period runs out and the session is gone."""
    manager = StreamableHTTPSessionManager(app=Server("test-get-stream"), session_idle_timeout=30)
    observer = _observe_idle_timeout(caplog, request)

    async with _served(manager) as http:
        initialize = await http.post("/mcp", content=_INITIALIZE_BODY, headers=_JSON_HEADERS)
        assert initialize.status_code == 200
        session_id = initialize.headers[MCP_SESSION_ID_HEADER]
        session_headers = _JSON_HEADERS | {MCP_SESSION_ID_HEADER: session_id}

        get_headers = {"accept": "text/event-stream", MCP_SESSION_ID_HEADER: session_id}
        async with http.stream("GET", "/mcp", headers=get_headers) as stream:
            assert stream.status_code == 200
            # The stream has been answered, so it is in flight: the idle countdown is suspended.
            transport = manager._server_instances[session_id]
            assert transport.idle_scope is not None and transport.idle_scope.deadline == math.inf
            # From here on a short idle period, counted from the moment the stream closes.
            transport._idle_timeout = 0.05

        with anyio.fail_after(5):
            await observer.reaped.wait()
        assert session_id not in manager._server_instances
        assert transport.is_terminated
        followup = await http.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "ping"}, headers=session_headers)
        assert followup.status_code == 404


@pytest.mark.anyio
async def test_request_completing_under_an_open_event_stream_does_not_start_the_countdown(
    caplog: pytest.LogCaptureFixture, request: pytest.FixtureRequest
) -> None:
    """A request that completes while the session's GET stream is still open does not start the idle
    period: the stream is still in flight, so the countdown only begins once it closes too."""
    manager = StreamableHTTPSessionManager(app=Server("test-get-stream-and-post"), session_idle_timeout=30)
    observer = _observe_idle_timeout(caplog, request)
    session_post_served = anyio.Event()

    async def endpoint(scope: Scope, receive: Receive, send: Send) -> None:
        # Report once a POST for the open session has been served to the end,
        # in-flight bookkeeping included.
        await manager.handle_request(scope, receive, send)
        if scope["method"] == "POST" and MCP_SESSION_ID_HEADER.encode() in dict(scope["headers"]):
            session_post_served.set()

    async with _served(manager, endpoint) as http:
        initialize = await http.post("/mcp", content=_INITIALIZE_BODY, headers=_JSON_HEADERS)
        assert initialize.status_code == 200
        session_id = initialize.headers[MCP_SESSION_ID_HEADER]
        session_headers = _JSON_HEADERS | {MCP_SESSION_ID_HEADER: session_id}

        get_headers = {"accept": "text/event-stream", MCP_SESSION_ID_HEADER: session_id}
        async with http.stream("GET", "/mcp", headers=get_headers) as stream:
            assert stream.status_code == 200
            transport = manager._server_instances[session_id]
            assert transport.idle_scope is not None and transport.idle_scope.deadline == math.inf
            ping = await http.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "ping"}, headers=session_headers)
            assert ping.status_code == 200
            with anyio.fail_after(5):
                await session_post_served.wait()
            # The ping has completed, but the open stream still suspends the idle countdown.
            assert transport.idle_scope.deadline == math.inf
            # From here on a short idle period, counted from the moment the stream closes.
            transport._idle_timeout = 0.05

        with anyio.fail_after(5):
            await observer.reaped.wait()
        assert session_id not in manager._server_instances
        assert transport.is_terminated
        followup = await http.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "ping"}, headers=session_headers)
        assert followup.status_code == 404


def test_session_idle_timeout_defaults_to_thirty_minutes() -> None:
    """Stateful sessions expire after 30 minutes without a request in flight unless configured otherwise."""
    manager = StreamableHTTPSessionManager(app=Server("test"))
    assert manager.session_idle_timeout == DEFAULT_SESSION_IDLE_TIMEOUT == 30 * 60


@pytest.mark.parametrize("session_idle_timeout", [0, -1, float("inf"), float("nan")])
def test_session_idle_timeout_rejects_invalid_values(session_idle_timeout: float) -> None:
    """The idle timeout is a positive, finite number of seconds, or None for sessions that never expire."""
    with pytest.raises(ValueError) as exc_info:
        StreamableHTTPSessionManager(app=Server("test"), session_idle_timeout=session_idle_timeout)
    assert str(exc_info.value) == "session_idle_timeout must be a positive, finite number of seconds"


@pytest.mark.anyio
async def test_session_idle_timeout_is_unused_in_stateless_mode() -> None:
    """Stateless mode keeps no sessions, so the idle timeout is accepted and simply has nothing to expire."""
    manager = StreamableHTTPSessionManager(app=Server("test"), session_idle_timeout=30, stateless=True)
    async with manager.run():
        response_start, _ = await _call(manager, _request_scope(), _INITIALIZE_BODY)
        assert response_start["status"] == 200
        assert manager._server_instances == {}


@pytest.mark.anyio
@pytest.mark.parametrize("session_idle_timeout", [DEFAULT_SESSION_IDLE_TIMEOUT, None])
async def test_deleted_session_is_forgotten(session_idle_timeout: float | None) -> None:
    """A client DELETE ends the session and the manager stops tracking it; the ID is unknown afterwards."""
    manager = StreamableHTTPSessionManager(app=Server("test-delete"), session_idle_timeout=session_idle_timeout)
    async with manager.run():
        session_id = await _open_session(manager, None)
        assert session_id in manager._server_instances

        assert await _request_session(manager, session_id, None, method="DELETE") == 200
        assert session_id not in manager._server_instances
        response_start, response_body = await _call(manager, _request_scope(session_id=session_id))
        assert response_start["status"] == 404
        assert json.loads(response_body) == {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": INVALID_REQUEST, "message": "Session not found"},
        }


@pytest.mark.anyio
async def test_opening_request_that_fails_leaves_no_session() -> None:
    """If serving the request that would open a session raises, the provisional session is discarded
    there and then rather than left registered with its server task running."""
    manager = StreamableHTTPSessionManager(app=Server("test-failed-open"))
    with _created_transports() as transports:
        async with manager.run():
            with (
                patch.object(
                    StreamableHTTPServerTransport, "handle_request", AsyncMock(side_effect=RuntimeError("boom"))
                ),
                pytest.raises(RuntimeError, match="boom"),
                anyio.fail_after(5),
            ):
                await _call(manager, _request_scope(), _INITIALIZE_BODY)
            assert manager._server_instances == {}
            assert manager._session_owners == {}
            (transport,) = transports
            assert transport.is_terminated


@pytest.mark.anyio
async def test_opening_request_that_is_cancelled_leaves_no_session() -> None:
    """If the request that would open a session is cancelled while it is being served (the client went
    away), the provisional session is discarded rather than left registered."""
    manager = StreamableHTTPSessionManager(app=Server("test-cancelled-open"))
    entered = anyio.Event()

    async def hang(self: StreamableHTTPServerTransport, scope: Scope, receive: Receive, send: Send) -> None:
        entered.set()
        await anyio.sleep_forever()

    opening_request = anyio.CancelScope()

    async def open_session() -> None:
        with opening_request:
            await _call(manager, _request_scope(), _INITIALIZE_BODY)

    with _created_transports() as transports, patch.object(StreamableHTTPServerTransport, "handle_request", hang):
        async with manager.run():
            async with anyio.create_task_group() as tg:
                tg.start_soon(open_session)
                with anyio.fail_after(5):
                    await entered.wait()
                assert len(manager._server_instances) == 1
                opening_request.cancel()
            assert manager._server_instances == {}
            assert manager._session_owners == {}
            (transport,) = transports
            assert transport.is_terminated


@pytest.mark.anyio
async def test_opening_request_whose_session_task_cannot_start_leaves_no_session() -> None:
    """If the server task for a would-be session cannot be started, the provisional session is discarded
    (forgotten, its transport terminated) rather than left registered without anything serving it."""
    manager = StreamableHTTPSessionManager(app=Server("test-unstartable-open"))

    @asynccontextmanager
    async def connect_that_fails(self: StreamableHTTPServerTransport) -> AsyncIterator[None]:
        raise RuntimeError("boom")
        yield

    with _created_transports() as transports:
        async with manager.run():
            with (
                patch.object(StreamableHTTPServerTransport, "connect", connect_that_fails),
                pytest.raises(RuntimeError, match="boom"),
                anyio.fail_after(5),
            ):
                await _call(manager, _request_scope(), _INITIALIZE_BODY)
            assert manager._server_instances == {}
            assert manager._session_owners == {}
            (transport,) = transports
            assert transport.is_terminated


@pytest.mark.anyio
async def test_stateless_request_that_is_cancelled_still_terminates_its_transport() -> None:
    """If a stateless request is cancelled while it is being served (the client went away), its transport
    is terminated all the same, which is what ends the per-request server task."""
    manager = StreamableHTTPSessionManager(app=Server("test-stateless-cancelled"), stateless=True)
    entered = anyio.Event()

    async def hang(self: StreamableHTTPServerTransport, scope: Scope, receive: Receive, send: Send) -> None:
        entered.set()
        await anyio.sleep_forever()

    stateless_request = anyio.CancelScope()

    async def make_request() -> None:
        with stateless_request:
            await _call(manager, _request_scope(), _INITIALIZE_BODY)

    with _created_transports() as transports, patch.object(StreamableHTTPServerTransport, "handle_request", hang):
        async with manager.run():
            async with anyio.create_task_group() as tg:
                tg.start_soon(make_request)
                with anyio.fail_after(5):
                    await entered.wait()
                stateless_request.cancel()
            (transport,) = transports
            assert transport.is_terminated


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "headers", "body", "expected_status"),
    [
        ("POST", _JSON_HEADERS, b'{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}', 400),
        ("POST", _JSON_HEADERS, b'{"jsonrpc": "2.0", "method": "notifications/initialized"}', 400),
        ("POST", _JSON_HEADERS, b"{not json", 400),
        ("POST", _JSON_HEADERS | {"accept": "text/plain"}, _INITIALIZE_BODY, 406),
        ("GET", {"accept": "text/event-stream"}, b"", 400),
        ("DELETE", _JSON_HEADERS, b"", 400),
        ("PATCH", _JSON_HEADERS, b"", 405),
    ],
    ids=[
        "non-initialize-request",
        "notification",
        "malformed-json",
        "unacceptable-accept-header",
        "get-without-session",
        "delete-without-session",
        "unsupported-method",
    ],
)
async def test_refused_opening_request_leaves_no_session(
    method: str, headers: dict[str, str], body: bytes, expected_status: int
) -> None:
    """Only an accepted initialize opens a session: a request without a session ID that is answered with an
    error leaves nothing registered once the manager has answered it."""
    manager = StreamableHTTPSessionManager(app=Server("test-refused"))
    scope: Scope = {
        "type": "http",
        "method": method,
        "path": "/mcp",
        "headers": [(name.encode(), value.encode()) for name, value in headers.items()],
    }
    with _created_transports() as transports:
        async with manager.run():
            response_start, _ = await _call(manager, scope, body)
            assert response_start["status"] == expected_status
            assert manager._server_instances == {}
            assert manager._session_owners == {}
            (transport,) = transports
            assert transport.is_terminated


@pytest.mark.anyio
async def test_new_session_is_refused_at_max_sessions() -> None:
    """At the session limit a further initialize is answered 503 and opens nothing; room frees up as
    sessions end."""
    manager = StreamableHTTPSessionManager(app=Server("test-cap"), max_sessions=1)
    async with manager.run():
        first = await _open_session(manager, None)

        response_start, response_body = await _call(manager, _request_scope(), _INITIALIZE_BODY)
        assert response_start["status"] == 503
        assert json.loads(response_body) == {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": INTERNAL_ERROR, "message": "Too many open sessions"},
        }
        assert list(manager._server_instances) == [first]

        assert await _request_session(manager, first, None, method="DELETE") == 200
        second = await _open_session(manager, None)
        assert list(manager._server_instances) == [second]


@pytest.mark.anyio
async def test_client_that_is_slow_to_send_its_opening_request_does_not_hold_up_others() -> None:
    """While one client has yet to finish sending the request that would open its session, another
    client can still open one."""
    manager = StreamableHTTPSessionManager(app=Server("test-slow-open"))
    body_awaited = anyio.Event()

    async def stall() -> None:
        # This client has sent its headers but never finishes sending the body.
        body_awaited.set()
        await anyio.sleep_forever()

    async def discard(message: Message) -> None: ...

    slow_client = anyio.CancelScope()

    async def open_slowly() -> None:
        with slow_client:
            await manager.handle_request(_request_scope(), cast(Receive, stall), discard)

    session_id: str | None = None
    async with manager.run():
        async with anyio.create_task_group() as tg:
            tg.start_soon(open_slowly)
            with anyio.fail_after(5):
                await body_awaited.wait()
                session_id = await _open_session(manager, None)
            slow_client.cancel()
        assert session_id is not None
        assert list(manager._server_instances) == [session_id]


def test_max_sessions_defaults_to_ten_thousand() -> None:
    """A manager holds at most 10 000 concurrent stateful sessions unless configured otherwise."""
    manager = StreamableHTTPSessionManager(app=Server("test"))
    assert manager.max_sessions == DEFAULT_MAX_SESSIONS == 10_000
    assert StreamableHTTPSessionManager(app=Server("test"), max_sessions=None).max_sessions is None


@pytest.mark.parametrize("max_sessions", [0, -1])
def test_max_sessions_rejects_non_positive_values(max_sessions: int) -> None:
    with pytest.raises(ValueError) as exc_info:
        StreamableHTTPSessionManager(app=Server("test"), max_sessions=max_sessions)
    assert str(exc_info.value) == "max_sessions must be a positive number of sessions or None"


def _user(client_id: str, subject: str | None = None, issuer: str | None = None) -> AuthenticatedUser:
    """Build the scope["user"] value that AuthenticationMiddleware would set for this principal."""
    claims = {"iss": issuer} if issuer is not None else None
    return AuthenticatedUser(AccessToken(token="token", client_id=client_id, scopes=[], subject=subject, claims=claims))


def _request_scope(
    *, session_id: str | None = None, user: AuthenticatedUser | None = None, method: str = "POST"
) -> Scope:
    """Build an ASGI scope for a request to the MCP endpoint."""
    headers = [
        (b"content-type", b"application/json"),
        (b"accept", b"application/json, text/event-stream"),
    ]
    if session_id is not None:
        headers.append((b"mcp-session-id", session_id.encode()))
    scope: Scope = {
        "type": "http",
        "method": method,
        "path": "/mcp",
        "headers": headers,
    }
    if user is not None:
        scope["user"] = user
    return scope


async def _call(manager: StreamableHTTPSessionManager, scope: Scope, body: bytes = b"") -> tuple[Message, bytes]:
    """Drive one request through the manager in process; return its `http.response.start` message and body."""
    sent_messages: list[Message] = []
    body_delivered = False

    async def send(message: Message) -> None:
        sent_messages.append(message)

    async def receive() -> Message:
        # Deliver the body once, then block like a client holding the connection
        # open; a streaming response ends when the server closes it.
        nonlocal body_delivered
        if body_delivered:
            await anyio.sleep_forever()
        body_delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    await manager.handle_request(scope, receive, send)
    response_start = next(msg for msg in sent_messages if msg["type"] == "http.response.start")
    response_body = b"".join(msg.get("body", b"") for msg in sent_messages if msg["type"] == "http.response.body")
    return response_start, response_body


async def _open_session(manager: StreamableHTTPSessionManager, user: AuthenticatedUser | None) -> str:
    """Create a new session as `user` with an initialize request and return its session ID."""
    response_start, _ = await _call(manager, _request_scope(user=user), _INITIALIZE_BODY)
    assert response_start["status"] == 200
    headers = dict(response_start.get("headers", []))
    return headers[MCP_SESSION_ID_HEADER.encode()].decode()


async def _request_session(
    manager: StreamableHTTPSessionManager, session_id: str, user: AuthenticatedUser | None, method: str = "POST"
) -> int:
    """Send a request for an existing session as `user` and return the response status."""
    response_start, _ = await _call(manager, _request_scope(session_id=session_id, user=user, method=method))
    return response_start["status"]


@pytest.fixture
async def manager_with_live_session():
    """A running manager around a real `Server`. Sessions are opened with a real initialize and stay
    registered until `manager.run()` exits because nothing in these tests ends them."""
    manager = StreamableHTTPSessionManager(app=Server("test-session-credentials"))
    async with manager.run():
        yield manager


@pytest.mark.anyio
async def test_session_accepts_requests_from_the_credential_that_created_it(
    manager_with_live_session: StreamableHTTPSessionManager,
) -> None:
    """Requests presenting the same credential as the one that created the session are served."""
    manager = manager_with_live_session
    session_id = await _open_session(manager, _user("client-a"))

    status = await _request_session(manager, session_id, _user("client-a"))

    # The request passes the manager's credential check and reaches the
    # session's transport, instead of being answered with 404 by the manager.
    assert status != 404


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["POST", "GET", "DELETE"])
async def test_session_rejects_requests_from_a_different_credential(
    manager_with_live_session: StreamableHTTPSessionManager, method: str
) -> None:
    """A session created by one credential cannot be used with another credential, whatever the method."""
    manager = manager_with_live_session
    session_id = await _open_session(manager, _user("client-a"))

    assert await _request_session(manager, session_id, _user("client-b"), method) == 404
    # The session is still registered and still serves its creator.
    assert await _request_session(manager, session_id, _user("client-a")) != 404


@pytest.mark.anyio
async def test_session_rejects_requests_from_a_different_subject_of_the_same_client(
    manager_with_live_session: StreamableHTTPSessionManager,
) -> None:
    """Two end-users that share an OAuth client cannot use each other's sessions."""
    manager = manager_with_live_session
    session_id = await _open_session(manager, _user("client-a", subject="alice"))

    assert await _request_session(manager, session_id, _user("client-a", subject="bob")) == 404
    assert await _request_session(manager, session_id, _user("client-a", subject=None)) == 404
    assert await _request_session(manager, session_id, _user("client-a", subject="alice")) != 404


@pytest.mark.anyio
async def test_session_rejects_requests_with_the_same_subject_from_a_different_issuer(
    manager_with_live_session: StreamableHTTPSessionManager,
) -> None:
    """A subject is unique only per issuer, so a colliding subject from a different issuer is not the same principal."""
    manager = manager_with_live_session
    creator = _user("client-a", subject="alice", issuer="https://issuer.one")
    session_id = await _open_session(manager, creator)

    other_issuer = _user("client-a", subject="alice", issuer="https://issuer.two")
    assert await _request_session(manager, session_id, other_issuer) == 404
    assert await _request_session(manager, session_id, _user("client-a", subject="alice")) == 404
    assert await _request_session(manager, session_id, creator) != 404


@pytest.mark.anyio
async def test_session_rejects_unauthenticated_requests_for_an_authenticated_session(
    manager_with_live_session: StreamableHTTPSessionManager,
) -> None:
    """A session created with a credential cannot be used without one."""
    manager = manager_with_live_session
    session_id = await _open_session(manager, _user("client-a"))

    assert await _request_session(manager, session_id, None) == 404


@pytest.mark.anyio
async def test_session_rejects_authenticated_requests_for_an_anonymous_session(
    manager_with_live_session: StreamableHTTPSessionManager,
) -> None:
    """A session created without a credential cannot be used with one."""
    manager = manager_with_live_session
    session_id = await _open_session(manager, None)

    assert await _request_session(manager, session_id, _user("client-a")) == 404


@pytest.mark.anyio
async def test_anonymous_session_accepts_anonymous_requests(
    manager_with_live_session: StreamableHTTPSessionManager,
) -> None:
    """Servers without authentication keep working: no credential on either side."""
    manager = manager_with_live_session
    session_id = await _open_session(manager, None)

    assert await _request_session(manager, session_id, None) != 404
