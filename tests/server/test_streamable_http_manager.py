"""Tests for StreamableHTTPSessionManager."""

import json
import logging
from typing import Any
from unittest.mock import AsyncMock, patch

import anyio
import httpx
import pytest
from starlette.types import Message, Scope

from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext, streamable_http_manager
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER, StreamableHTTPServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import INVALID_REQUEST, ListToolsResult, PaginatedRequestParams


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
async def test_run_terminates_active_transports_before_shutdown():
    app = Server("test-server")
    manager = StreamableHTTPSessionManager(app=app)
    transport = AsyncMock()

    async with manager.run():
        manager._server_instances["session-id"] = transport

    transport.terminate.assert_awaited_once_with()
    assert not manager._server_instances


@pytest.mark.anyio
async def test_handle_request_without_run_raises_error():
    """Test that handle_request raises error if run() hasn't been called."""
    app = Server("test-server")
    manager = StreamableHTTPSessionManager(app=app)

    # Mock ASGI parameters
    scope = {"type": "http", "method": "POST", "path": "/test"}

    async def receive():  # pragma: no cover
        return {"type": "http.request", "body": b""}

    async def send(message: Message):  # pragma: no cover
        pass

    # Should raise error because run() hasn't been called
    with pytest.raises(RuntimeError) as excinfo:
        await manager.handle_request(scope, receive, send)

    assert "Task group is not initialized. Make sure to use run()." in str(excinfo.value)


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

    async def mock_receive():  # pragma: no cover
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

    async def mock_receive():  # pragma: no cover
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

    # Track created transport instances
    created_transports: list[StreamableHTTPServerTransport] = []

    # Patch StreamableHTTPServerTransport constructor to track instances

    original_constructor = StreamableHTTPServerTransport

    def track_transport(*args: Any, **kwargs: Any) -> StreamableHTTPServerTransport:
        transport = original_constructor(*args, **kwargs)
        created_transports.append(transport)
        return transport

    with patch.object(streamable_http_manager, "StreamableHTTPServerTransport", side_effect=track_transport):
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
async def test_transport_terminate_closes_active_sse_writers():
    transport = StreamableHTTPServerTransport(mcp_session_id="session-id")
    writer, reader = anyio.create_memory_object_stream[dict[str, str]](1)
    transport._sse_stream_writers["request-id"] = writer

    await transport.terminate()

    assert transport.is_terminated
    assert not transport._sse_stream_writers
    with pytest.raises(anyio.ClosedResourceError):
        writer.send_nowait({"event": "message", "data": "{}"})

    await reader.aclose()


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
            return {"type": "http.request", "body": b"{}", "more_body": False}  # pragma: no cover

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
        httpx.ASGITransport(mcp_app) as transport,
        httpx.AsyncClient(transport=transport) as http_client,
        Client(streamable_http_client(f"http://{host}/mcp", http_client=http_client)) as client,
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


@pytest.mark.anyio
async def test_idle_session_is_reaped(caplog: pytest.LogCaptureFixture, request: pytest.FixtureRequest):
    """After idle timeout fires, the session returns 404."""
    app = Server("test-idle-reap")
    manager = StreamableHTTPSessionManager(app=app, session_idle_timeout=0.05)

    # The reap is observed through the manager's own "idle timeout" log record: the manager pops
    # the session synchronously after emitting it, before its next await, so a waiter woken by
    # the record always finds the session gone. caplog.set_level enables INFO so it is created.
    observer = _IdleTimeoutObserver()
    manager_logger = logging.getLogger(streamable_http_manager.__name__)
    manager_logger.addHandler(observer)
    request.addfinalizer(lambda: manager_logger.removeHandler(observer))
    caplog.set_level(logging.INFO, logger=streamable_http_manager.__name__)

    async with manager.run():
        sent_messages: list[Message] = []

        async def mock_send(message: Message):
            sent_messages.append(message)

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [(b"content-type", b"application/json")],
        }

        async def mock_receive():  # pragma: no cover
            return {"type": "http.request", "body": b"", "more_body": False}

        await manager.handle_request(scope, mock_receive, mock_send)

        session_id = None
        for msg in sent_messages:  # pragma: no branch
            if msg["type"] == "http.response.start":  # pragma: no branch
                for header_name, header_value in msg.get("headers", []):  # pragma: no branch
                    if header_name.decode().lower() == MCP_SESSION_ID_HEADER.lower():
                        session_id = header_value.decode()
                        break
                if session_id:  # pragma: no branch
                    break

        assert session_id is not None, "Session ID not found in response headers"

        # Wait for the 50ms idle timeout to fire and the session to be unregistered. Re-requesting
        # the session to poll for the 404 would push its idle deadline forward and keep it alive.
        with anyio.fail_after(5):
            await observer.reaped.wait()

        # Verify via public API: old session ID now returns 404
        response_messages: list[Message] = []

        async def capture_send(message: Message):
            response_messages.append(message)

        scope_with_session = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [
                (b"content-type", b"application/json"),
                (b"mcp-session-id", session_id.encode()),
            ],
        }

        await manager.handle_request(scope_with_session, mock_receive, capture_send)

        response_start = next(
            (msg for msg in response_messages if msg["type"] == "http.response.start"),
            None,
        )
        assert response_start is not None
        assert response_start["status"] == 404


def test_session_idle_timeout_rejects_non_positive():
    with pytest.raises(ValueError, match="positive number"):
        StreamableHTTPSessionManager(app=Server("test"), session_idle_timeout=-1)
    with pytest.raises(ValueError, match="positive number"):
        StreamableHTTPSessionManager(app=Server("test"), session_idle_timeout=0)


def test_session_idle_timeout_rejects_stateless():
    with pytest.raises(RuntimeError, match="not supported in stateless"):
        StreamableHTTPSessionManager(app=Server("test"), session_idle_timeout=30, stateless=True)


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


async def _open_session(manager: StreamableHTTPSessionManager, user: AuthenticatedUser | None) -> str:
    """Create a new session as `user` and return its session ID."""
    sent_messages: list[Message] = []

    async def mock_send(message: Message) -> None:
        sent_messages.append(message)

    async def mock_receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    await manager.handle_request(_request_scope(user=user), mock_receive, mock_send)

    response_start = next(msg for msg in sent_messages if msg["type"] == "http.response.start")
    headers = dict(response_start.get("headers", []))
    return headers[MCP_SESSION_ID_HEADER.encode()].decode()


async def _request_session(
    manager: StreamableHTTPSessionManager, session_id: str, user: AuthenticatedUser | None, method: str = "POST"
) -> int:
    """Send a request for an existing session as `user` and return the response status."""
    sent_messages: list[Message] = []

    async def mock_send(message: Message) -> None:
        sent_messages.append(message)

    async def mock_receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    await manager.handle_request(
        _request_scope(session_id=session_id, user=user, method=method), mock_receive, mock_send
    )

    response_start = next(msg for msg in sent_messages if msg["type"] == "http.response.start")
    return response_start["status"]


@pytest.fixture
async def manager_with_live_session():
    """A running manager around a real `Server`. Sessions remain registered until
    `manager.run()` exits because `Server.run` blocks waiting for an initialize message."""
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
