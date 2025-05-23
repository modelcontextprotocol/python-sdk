"""Tests for StreamableHTTPSessionManager."""

import json

import anyio
import pytest

from mcp.server.lowlevel import Server
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

    assert (
        "StreamableHTTPSessionManager .run() can only be called once per instance"
        in str(excinfo.value)
    )


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
    assert (
        "StreamableHTTPSessionManager .run() can only be called once per instance"
        in str(errors[0])
    )


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
        del message  # Suppress unused parameter warning

    # Should raise error because run() hasn't been called
    with pytest.raises(RuntimeError) as excinfo:
        await manager.handle_request(scope, receive, send)

    assert "Task group is not initialized. Make sure to use run()." in str(
        excinfo.value
    )


@pytest.mark.anyio
async def test_session_cleanup_on_delete_request():
    """Test sessions are properly cleaned up when DELETE request terminates them."""
    app = Server("test-server")
    manager = StreamableHTTPSessionManager(app=app, json_response=True, stateless=False)

    async with manager.run():
        # Create a new session by making a POST request
        session_id = None

        # Mock ASGI parameters for POST request (session creation)
        post_scope = {
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [
                (b"content-type", b"application/json"),
                (b"accept", b"application/json, text/event-stream"),
            ],
        }

        # Mock initialization request
        init_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        }

        post_body = json.dumps(init_request).encode()
        post_request_body_sent = False

        async def post_receive():
            nonlocal post_request_body_sent
            if not post_request_body_sent:
                post_request_body_sent = True
                return {"type": "http.request", "body": post_body}
            else:
                return {"type": "http.request", "body": b""}

        response_data = {}

        async def post_send(message):
            if message["type"] == "http.response.start":
                response_data["status"] = message["status"]
                response_data["headers"] = dict(message.get("headers", []))
            elif message["type"] == "http.response.body":
                response_data["body"] = message.get("body", b"")

        # Make POST request to create session
        await manager.handle_request(post_scope, post_receive, post_send)

        # Extract session ID from response headers
        session_id = response_data["headers"].get(b"mcp-session-id")
        if session_id:
            session_id = session_id.decode()

        # Verify session was created
        assert session_id is not None
        assert session_id in manager._server_instances

        # Now make DELETE request to terminate session
        delete_scope = {
            "type": "http",
            "method": "DELETE",
            "path": "/test",
            "headers": [(b"mcp-session-id", session_id.encode())],
        }

        async def delete_receive():
            return {"type": "http.request", "body": b""}

        delete_response_data = {}

        async def delete_send(message):
            if message["type"] == "http.response.start":
                delete_response_data["status"] = message["status"]

        # Make DELETE request
        await manager.handle_request(delete_scope, delete_receive, delete_send)

        # Verify DELETE request succeeded
        assert delete_response_data["status"] == 200

        # Give a moment for the callback to execute
        await anyio.sleep(0.01)

        # Verify session was removed from manager
        assert session_id not in manager._server_instances
