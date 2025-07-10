"""Tests for StreamableHTTPSessionManager."""

from unittest.mock import AsyncMock

import anyio
import pytest

from mcp.server.lowlevel import Server
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER
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

    errors = []

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

    async def send(message):
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
async def test_stateful_session_cleanup_on_graceful_exit(running_manager):
    manager, app = running_manager

    mock_mcp_run = AsyncMock(return_value=None)
    # This will be called by StreamableHTTPSessionManager's run_server -> self.app.run
    app.run = mock_mcp_run

    sent_messages = []

    async def mock_send(message):
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
async def test_stateful_session_cleanup_on_exception(running_manager):
    manager, app = running_manager

    mock_mcp_run = AsyncMock(side_effect=TestException("Simulated crash"))
    app.run = mock_mcp_run

    sent_messages = []

    async def mock_send(message):
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
