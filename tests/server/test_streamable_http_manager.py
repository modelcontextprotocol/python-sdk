"""Tests for StreamableHTTPSessionManager."""

import json
import logging
from typing import Any
from unittest.mock import AsyncMock, patch

import anyio
import httpx
import pytest
from starlette.types import Message

from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext, streamable_http_manager
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
    manager, app = running_manager

    mock_mcp_run = AsyncMock(return_value=None)
    # This will be called by StreamableHTTPSessionManager's run_server -> self.app.run
    app.run = mock_mcp_run

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

    # Ensure MCPServer.run was called
    mock_mcp_run.assert_called_once()

    # At this point, mock_mcp_run has completed, and the finally block in
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
    manager, app = running_manager

    mock_mcp_run = AsyncMock(side_effect=TestException("Simulated crash"))
    app.run = mock_mcp_run

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

    mock_mcp_run.assert_called_once()

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
            # Mock app.run to complete immediately
            app.run = AsyncMock(return_value=None)

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


@pytest.mark.anyio
async def test_idle_session_is_reaped():
    """After idle timeout fires, the session returns 404."""
    app = Server("test-idle-reap")
    manager = StreamableHTTPSessionManager(app=app, session_idle_timeout=0.05)

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

        # Wait for the 50ms idle timeout to fire and cleanup to complete
        await anyio.sleep(0.1)

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


# --- Multi-tenancy: session-level tenant isolation ---


def _extract_session_id(messages: list[Message]) -> str | None:
    """Extract the MCP session ID from ASGI response messages."""
    for msg in messages:
        if msg["type"] == "http.response.start":
            for header_name, header_value in msg.get("headers", []):
                if header_name.decode().lower() == MCP_SESSION_ID_HEADER.lower():
                    return header_value.decode()
    return None


def _extract_status(messages: list[Message]) -> int | None:
    """Extract the HTTP status code from ASGI response messages."""
    for msg in messages:
        if msg["type"] == "http.response.start":
            return msg["status"]
    return None


def test_extract_session_id_skips_non_start_messages():
    """_extract_session_id skips non-start messages and returns None when no ID found."""
    body_msg: Message = {"type": "http.response.body", "body": b"data"}
    start_no_header: Message = {"type": "http.response.start", "status": 200, "headers": []}

    # Only body messages → None
    assert _extract_session_id([body_msg]) is None
    # Start message without session header → None
    assert _extract_session_id([body_msg, start_no_header]) is None


def test_extract_status_skips_non_start_messages():
    """_extract_status skips non-start messages and returns None when empty."""
    body_msg: Message = {"type": "http.response.body", "body": b"data"}
    start_msg: Message = {"type": "http.response.start", "status": 200, "headers": []}

    # Only body messages → None
    assert _extract_status([body_msg]) is None
    # Body then start → returns status from start
    assert _extract_status([body_msg, start_msg]) == 200
    # Empty list → None
    assert _extract_status([]) is None


def _make_scope(session_id: str | None = None) -> dict[str, Any]:
    """Build a minimal ASGI scope for testing, optionally with a session ID."""
    headers: list[tuple[bytes, bytes]] = [(b"content-type", b"application/json")]
    if session_id is not None:
        headers.append((b"mcp-session-id", session_id.encode()))
    return {"type": "http", "method": "POST", "path": "/mcp", "headers": headers}


async def _mock_send(messages: list[Message], message: Message) -> None:
    """Async send that collects messages."""
    messages.append(message)


async def _mock_receive() -> dict[str, Any]:  # pragma: no cover
    return {"type": "http.request", "body": b"", "more_body": False}


def _set_tenant(tenant: str | None) -> Any:
    """Set tenant_id_var if tenant is not None; return the token (or None)."""
    from mcp.shared._context import tenant_id_var

    return tenant_id_var.set(tenant) if tenant is not None else None


def _reset_tenant(token: Any) -> None:
    """Reset tenant_id_var if a token was set."""
    from mcp.shared._context import tenant_id_var

    if token is not None:
        tenant_id_var.reset(token)


async def _create_session_blocking(
    manager: StreamableHTTPSessionManager,
    app: Server[Any],
    stop_event: anyio.Event,
    tenant: str | None = None,
) -> str:
    """Create a session whose server stays alive until stop_event is set."""

    async def blocking_run(*args: Any, **kwargs: Any) -> None:
        await stop_event.wait()

    app.run = AsyncMock(side_effect=blocking_run)

    messages: list[Message] = []
    token = _set_tenant(tenant)
    try:
        await manager.handle_request(
            _make_scope(), _mock_receive, lambda msg, _msgs=messages: _mock_send(_msgs, msg)
        )
    finally:
        _reset_tenant(token)

    session_id = _extract_session_id(messages)
    assert session_id is not None
    return session_id


async def _access_session(
    manager: StreamableHTTPSessionManager,
    session_id: str,
    tenant: str | None = None,
) -> int | None:
    """Access an existing session and return the HTTP status code."""
    messages: list[Message] = []
    token = _set_tenant(tenant)
    try:
        await manager.handle_request(
            _make_scope(session_id), _mock_receive, lambda msg, _msgs=messages: _mock_send(_msgs, msg)
        )
    finally:
        _reset_tenant(token)

    return _extract_status(messages)


@pytest.mark.anyio
async def test_tenant_mismatch_returns_404(running_manager: tuple[StreamableHTTPSessionManager, Server]):
    """A request from tenant-b cannot access a session created by tenant-a."""
    manager, app = running_manager
    stop = anyio.Event()
    session_id = await _create_session_blocking(manager, app, stop, tenant="tenant-a")

    assert await _access_session(manager, session_id, tenant="tenant-b") == 404
    stop.set()


@pytest.mark.anyio
async def test_two_tenants_cannot_access_each_others_sessions(
    running_manager: tuple[StreamableHTTPSessionManager, Server],
):
    """Two tenants each create a session; neither can access the other's."""
    manager, app = running_manager
    stop = anyio.Event()

    session_a = await _create_session_blocking(manager, app, stop, tenant="tenant-a")
    session_b = await _create_session_blocking(manager, app, stop, tenant="tenant-b")
    assert session_a != session_b

    # Tenant-a tries to access tenant-b's session → 404
    assert await _access_session(manager, session_b, tenant="tenant-a") == 404
    # Tenant-b tries to access tenant-a's session → 404
    assert await _access_session(manager, session_a, tenant="tenant-b") == 404
    stop.set()


@pytest.mark.anyio
async def test_same_tenant_can_reuse_session(running_manager: tuple[StreamableHTTPSessionManager, Server]):
    """A request from the same tenant can access its own session."""
    manager, app = running_manager
    stop = anyio.Event()
    session_id = await _create_session_blocking(manager, app, stop, tenant="tenant-a")

    status = await _access_session(manager, session_id, tenant="tenant-a")
    assert status != 404, "Same tenant should be able to reuse its own session"
    stop.set()


@pytest.mark.anyio
async def test_no_tenant_session_allows_any_access(running_manager: tuple[StreamableHTTPSessionManager, Server]):
    """Sessions created without a tenant (no auth) allow access from any request."""
    manager, app = running_manager
    stop = anyio.Event()
    session_id = await _create_session_blocking(manager, app, stop, tenant=None)

    status = await _access_session(manager, session_id, tenant="tenant-a")
    assert status != 404, "Session without tenant binding should allow access from any tenant"
    stop.set()


@pytest.mark.anyio
async def test_unauthenticated_request_cannot_access_tenant_session(
    running_manager: tuple[StreamableHTTPSessionManager, Server],
):
    """A request with no tenant cannot access a session bound to a tenant."""
    manager, app = running_manager
    stop = anyio.Event()
    session_id = await _create_session_blocking(manager, app, stop, tenant="tenant-a")

    assert await _access_session(manager, session_id, tenant=None) == 404
    stop.set()


@pytest.mark.anyio
async def test_session_tenant_cleanup_on_exit(running_manager: tuple[StreamableHTTPSessionManager, Server]):
    """Tenant mapping is cleaned up when a session exits."""
    manager, app = running_manager
    app.run = AsyncMock(return_value=None)

    messages: list[Message] = []
    token = _set_tenant("tenant-a")
    try:
        await manager.handle_request(
            _make_scope(), _mock_receive, lambda msg, _msgs=messages: _mock_send(_msgs, msg)
        )
    finally:
        _reset_tenant(token)

    session_id = _extract_session_id(messages)
    assert session_id is not None

    # Wait for the mock server to complete and cleanup to run
    await anyio.sleep(0.01)

    assert session_id not in manager._session_tenants, "Tenant mapping should be cleaned up after session exits"
