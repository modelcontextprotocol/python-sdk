"""Tests for StreamableHTTPSessionManager."""

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest
from starlette.types import Message

from mcp.server import streamable_http_manager
from mcp.server.lowlevel import Server
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER, StreamableHTTPServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager


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
            pass

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

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message: Message):
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

    async def mock_receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    # Trigger session creation
    await manager.handle_request(scope, mock_receive, mock_send)

    # Extract session ID from response headers
    session_id = None
    for msg in sent_messages:
        if msg["type"] == "http.response.start":
            for header_name, header_value in msg.get("headers", []):
                if header_name.decode().lower() == MCP_SESSION_ID_HEADER.lower():
                    session_id = header_value.decode()
                    break
            if session_id:  # Break outer loop if session_id is found
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
        if message["type"] == "http.response.start" and message["status"] >= 500:
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
    await manager.handle_request(scope, mock_receive, mock_send)

    session_id = None
    for msg in sent_messages:
        if msg["type"] == "http.response.start":
            for header_name, header_value in msg.get("headers", []):
                if header_name.decode().lower() == MCP_SESSION_ID_HEADER.lower():
                    session_id = header_value.decode()
                    break
            if session_id:  # Break outer loop if session_id is found
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

    original_constructor = streamable_http_manager.StreamableHTTPServerTransport

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
async def test_idle_session_cleanup():
    """Test that idle sessions are cleaned up when threshold is exceeded."""
    app = Server("test-idle-cleanup")

    # Use very short timeouts for testing
    manager = StreamableHTTPSessionManager(
        app=app,
        session_idle_timeout=0.5,  # 500ms idle timeout
        cleanup_check_interval=0.2,  # Check every 200ms
        max_sessions_before_cleanup=2,  # Low threshold for testing
    )

    async with manager.run():
        # Mock the app.run to prevent it from doing anything

        async def mock_infinite_sleep(*args: Any, **kwargs: Any) -> None:
            await anyio.sleep(float("inf"))

        app.run = AsyncMock(side_effect=mock_infinite_sleep)

        # Create mock transports directly to simulate sessions
        # We'll bypass the HTTP layer for simplicity
        session_ids = ["session1", "session2", "session3"]

        for session_id in session_ids:
            # Create a mock transport
            transport = MagicMock(spec=StreamableHTTPServerTransport)
            transport.mcp_session_id = session_id
            transport.is_terminated = False
            transport.terminate = AsyncMock()

            # Add to manager's tracking
            manager._server_instances[session_id] = transport
            manager._session_last_activity[session_id] = time.time()

        # Verify all sessions are tracked
        assert len(manager._server_instances) == 3
        assert len(manager._session_last_activity) == 3

        # Wait for cleanup to trigger (sessions should be idle long enough)
        await anyio.sleep(1.0)  # Wait longer than idle timeout + cleanup interval

        # All sessions should be cleaned up since they exceeded idle timeout
        assert len(manager._server_instances) == 0, "All idle sessions should be cleaned up"
        assert len(manager._session_last_activity) == 0, "Activity tracking should be cleared"


@pytest.mark.anyio
async def test_cleanup_only_above_threshold():
    """Test that cleanup only runs when session count exceeds threshold."""
    app = Server("test-threshold")

    # Set high threshold so cleanup won't run
    manager = StreamableHTTPSessionManager(
        app=app,
        session_idle_timeout=0.1,  # Very short idle timeout
        cleanup_check_interval=0.1,  # Check frequently
        max_sessions_before_cleanup=100,  # High threshold
    )

    async with manager.run():

        async def mock_infinite_sleep(*args: Any, **kwargs: Any) -> None:
            await anyio.sleep(float("inf"))

        app.run = AsyncMock(side_effect=mock_infinite_sleep)

        # Create just one session (below threshold)
        transport = MagicMock(spec=StreamableHTTPServerTransport)
        transport.mcp_session_id = "session1"
        transport.is_terminated = False
        transport.terminate = AsyncMock()

        manager._server_instances["session1"] = transport
        manager._session_last_activity["session1"] = time.time()

        # Wait longer than idle timeout
        await anyio.sleep(0.5)

        # Session should NOT be cleaned up because we're below threshold
        assert len(manager._server_instances) == 1, "Session should not be cleaned when below threshold"
        assert "session1" in manager._server_instances
        transport.terminate.assert_not_called()


@pytest.mark.anyio
async def test_session_activity_update():
    """Test that session activity is properly updated on requests."""
    app = Server("test-activity-update")
    manager = StreamableHTTPSessionManager(app=app)

    async with manager.run():
        # Create a session with known activity time
        old_time = time.time() - 100  # 100 seconds ago

        transport = MagicMock(spec=StreamableHTTPServerTransport)
        transport.mcp_session_id = "test-session"
        transport.handle_request = AsyncMock()

        manager._server_instances["test-session"] = transport
        manager._session_last_activity["test-session"] = old_time

        # Simulate a request to existing session
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [
                (b"mcp-session-id", b"test-session"),
                (b"content-type", b"application/json"),
                (b"accept", b"application/json, text/event-stream"),
            ],
        }

        async def mock_receive():
            return {"type": "http.request", "body": b'{"jsonrpc":"2.0","method":"test","id":1}', "more_body": False}

        async def mock_send(message: Message):
            pass

        # Handle the request
        await manager.handle_request(scope, mock_receive, mock_send)

        # Activity time should be updated
        new_time = manager._session_last_activity["test-session"]
        assert new_time > old_time, "Activity time should be updated"
        assert new_time >= time.time() - 1, "Activity time should be recent"
