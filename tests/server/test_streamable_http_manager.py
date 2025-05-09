"""Tests for StreamableHTTPSessionManager."""

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
        pass

    # Should raise error because run() hasn't been called
    with pytest.raises(RuntimeError) as excinfo:
        await manager.handle_request(scope, receive, send)

    assert "Task group is not initialized. Make sure to use run()." in str(
        excinfo.value
    )
