"""Tests for session roaming functionality with EventStore.

These tests verify that sessions can roam across different manager instances
when an EventStore is provided, enabling distributed deployments without sticky sessions.
"""

import contextlib
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import anyio
import pytest
from starlette.types import Message

from mcp.server.lowlevel import Server
from mcp.server.streamable_http import (
    MCP_SESSION_ID_HEADER,
    EventCallback,
    EventId,
    EventMessage,
    EventStore,
    StreamId,
)
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import JSONRPCMessage


async def mock_app_run(*args: Any, **kwargs: Any) -> None:
    """Mock app.run that blocks until cancelled instead of completing immediately."""
    try:
        await anyio.sleep_forever()
    except anyio.get_cancelled_exc_class():
        # Task was cancelled, which is expected when test exits
        pass


class SimpleEventStore(EventStore):
    """Simple in-memory event store for testing session roaming."""

    def __init__(self):
        self._events: list[tuple[StreamId, EventId, JSONRPCMessage]] = []
        self._event_id_counter = 0

    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage) -> EventId:
        """Store an event and return its ID."""
        self._event_id_counter += 1
        event_id = str(self._event_id_counter)
        self._events.append((stream_id, event_id, message))
        return event_id

    async def replay_events_after(
        self,
        last_event_id: EventId,
        send_callback: EventCallback,
    ) -> StreamId | None:
        """Replay events after the specified ID."""
        # Find the stream ID of the last event
        target_stream_id = None
        for stream_id, event_id, _ in self._events:
            if event_id == last_event_id:
                target_stream_id = stream_id
                break

        if target_stream_id is None:
            return None

        # Convert last_event_id to int for comparison
        last_event_id_int = int(last_event_id)

        # Replay only events from the same stream with ID > last_event_id
        for stream_id, event_id, message in self._events:
            if stream_id == target_stream_id and int(event_id) > last_event_id_int:
                await send_callback(EventMessage(message, event_id))

        return target_stream_id


@pytest.mark.anyio
async def test_session_roaming_with_eventstore():
    """Test that sessions can roam to a new manager instance when EventStore exists."""
    app = Server("test-roaming-server")
    event_store = SimpleEventStore()

    # Create first manager instance (simulating pod 1)
    manager1 = StreamableHTTPSessionManager(app=app, event_store=event_store)

    # Mock app.run to block until cancelled
    app.run = mock_app_run  # type: ignore[method-assign]

    sent_messages: list[Message] = []

    async def mock_send(message: Message) -> None:
        sent_messages.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"content-type", b"application/json")],
    }

    async def mock_receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    # Start manager1 and create a session
    async with manager1.run():
        # Create session on manager1
        await manager1.handle_request(scope, mock_receive, mock_send)

        # Extract session ID
        session_id = None
        for msg in sent_messages:
            if msg["type"] == "http.response.start":
                for header_name, header_value in msg.get("headers", []):
                    if header_name.decode().lower() == MCP_SESSION_ID_HEADER.lower():
                        session_id = header_value.decode()
                        break
                if session_id:
                    break

        assert session_id is not None, "Session ID should be created"

        # Verify session exists in manager1
        assert session_id in manager1._server_instances  # type: ignore[attr-defined]

    # Clear messages for second manager
    sent_messages.clear()

    # Create second manager instance (simulating pod 2)
    manager2 = StreamableHTTPSessionManager(app=app, event_store=event_store)

    # Mock app.run for manager2
    app.run = mock_app_run  # type: ignore[method-assign]

    # Start manager2 and use the session from manager1
    async with manager2.run():
        # Session should NOT exist in manager2 initially
        assert session_id not in manager2._server_instances  # type: ignore[attr-defined]

        # Make request with the session ID from manager1
        scope_with_session = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [
                (b"content-type", b"application/json"),
                (MCP_SESSION_ID_HEADER.encode(), session_id.encode()),
            ],
        }

        # This should trigger session roaming
        await manager2.handle_request(scope_with_session, mock_receive, mock_send)

        # Give the background task time to start
        await anyio.sleep(0.01)

        # Session should now exist in manager2 (roamed from manager1)
        assert session_id in manager2._server_instances, "Session should roam to manager2"  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_session_roaming_without_eventstore_rejects():
    """Test that unknown sessions are rejected when no EventStore is provided."""
    app = Server("test-no-roaming-server")

    # Create manager WITHOUT EventStore
    manager = StreamableHTTPSessionManager(app=app, event_store=None)

    sent_messages: list[Message] = []

    async def mock_send(message: Message) -> None:
        sent_messages.append(message)

    async def mock_receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async with manager.run():
        # Try to use a non-existent session ID
        scope_with_session = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [
                (b"content-type", b"application/json"),
                (MCP_SESSION_ID_HEADER.encode(), b"unknown-session-id"),
            ],
        }

        await manager.handle_request(scope_with_session, mock_receive, mock_send)

        # Should get a Bad Request response
        response_started = False
        for msg in sent_messages:
            if msg["type"] == "http.response.start":
                response_started = True
                assert msg["status"] == 400, "Should reject unknown session without EventStore"
                break

        assert response_started, "Should send response"


@pytest.mark.anyio
async def test_session_roaming_concurrent_requests():
    """Test that concurrent requests for the same roaming session don't create duplicates."""
    app = Server("test-concurrent-roaming")
    event_store = SimpleEventStore()

    # Create first manager and a session
    manager1 = StreamableHTTPSessionManager(app=app, event_store=event_store)
    app.run = mock_app_run  # type: ignore[method-assign]

    sent_messages: list[Message] = []

    async def mock_send(message: Message) -> None:
        sent_messages.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"content-type", b"application/json")],
    }

    async def mock_receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    # Create session on manager1
    async with manager1.run():
        await manager1.handle_request(scope, mock_receive, mock_send)

        # Extract session ID
        session_id = None
        for msg in sent_messages:
            if msg["type"] == "http.response.start":
                for header_name, header_value in msg.get("headers", []):
                    if header_name.decode().lower() == MCP_SESSION_ID_HEADER.lower():
                        session_id = header_value.decode()
                        break
                if session_id:
                    break

        assert session_id is not None

    # Create second manager
    manager2 = StreamableHTTPSessionManager(app=app, event_store=event_store)
    app.run = mock_app_run  # type: ignore[method-assign]

    async with manager2.run():
        # Make two concurrent requests with the same roaming session ID
        scope_with_session = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [
                (b"content-type", b"application/json"),
                (MCP_SESSION_ID_HEADER.encode(), session_id.encode()),
            ],
        }

        async def make_request() -> list[Message]:
            sent: list[Message] = []

            async def local_send(message: Message) -> None:
                sent.append(message)

            await manager2.handle_request(scope_with_session, mock_receive, local_send)
            return sent

        # Make concurrent requests
        async with anyio.create_task_group() as tg:
            tg.start_soon(make_request)
            tg.start_soon(make_request)

        # Give tasks time to complete
        await anyio.sleep(0.01)

        # Should only have one transport instance (no duplicates)
        assert len(manager2._server_instances) == 1, "Should only create one transport for concurrent requests"  # type: ignore[attr-defined]
        assert session_id in manager2._server_instances  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_transport_server_task_cleanup_on_exception():
    """Test that _transport_server_task properly cleans up when an exception occurs."""
    app = Server("test-cleanup")
    manager = StreamableHTTPSessionManager(app=app)

    # Create a mock transport
    from unittest.mock import patch

    from mcp.server.streamable_http import StreamableHTTPServerTransport

    transport = StreamableHTTPServerTransport(mcp_session_id="test-session-cleanup")

    # Mock the app.run to raise an exception
    app.run = AsyncMock(side_effect=Exception("Simulated crash"))  # type: ignore[method-assign]

    # Mock transport.connect to return streams
    mock_read_stream = AsyncMock()
    mock_write_stream = AsyncMock()

    @contextlib.asynccontextmanager
    async def mock_connect() -> AsyncIterator[tuple[AsyncMock, AsyncMock]]:
        yield (mock_read_stream, mock_write_stream)

    async with manager.run():
        # Manually add transport to instances
        manager._server_instances["test-session-cleanup"] = transport  # type: ignore[attr-defined]

        with patch.object(transport, "connect", mock_connect):
            # Run the transport server task
            await manager._start_transport_server(transport)

            # Give time for exception handling
            await anyio.sleep(0.01)

            # Transport should be removed from instances after crash
            assert "test-session-cleanup" not in manager._server_instances, (  # type: ignore[attr-defined]
                "Crashed session should be removed from instances"
            )


@pytest.mark.anyio
async def test_transport_server_task_no_cleanup_on_terminated():
    """Test that _transport_server_task doesn't remove already-terminated transports."""
    app = Server("test-no-cleanup-terminated")
    manager = StreamableHTTPSessionManager(app=app)

    from unittest.mock import patch

    from mcp.server.streamable_http import StreamableHTTPServerTransport

    transport = StreamableHTTPServerTransport(mcp_session_id="test-session-terminated")

    # Mark transport as terminated
    transport._terminated = True  # type: ignore[attr-defined]

    # Mock the app.run to complete normally
    app.run = AsyncMock(return_value=None)  # type: ignore[method-assign]

    # Mock transport.connect to return streams
    mock_read_stream = AsyncMock()
    mock_write_stream = AsyncMock()

    @contextlib.asynccontextmanager
    async def mock_connect() -> AsyncIterator[tuple[AsyncMock, AsyncMock]]:
        yield (mock_read_stream, mock_write_stream)

    async with manager.run():
        # Manually add transport to instances
        manager._server_instances["test-session-terminated"] = transport  # type: ignore[attr-defined]

        with patch.object(transport, "connect", mock_connect):
            # Run the transport server task
            await manager._start_transport_server(transport)

            # Give time for task to complete
            await anyio.sleep(0.01)

            # Transport should STILL be in instances (not removed because it was already terminated)
            assert "test-session-terminated" in manager._server_instances, (  # type: ignore[attr-defined]
                "Terminated transport should not be removed by cleanup"
            )


@pytest.mark.anyio
async def test_session_roaming_fast_path_unchanged():
    """Test that existing sessions still use fast path (no EventStore query)."""
    app = Server("test-fast-path")
    event_store = SimpleEventStore()
    manager = StreamableHTTPSessionManager(app=app, event_store=event_store)

    app.run = mock_app_run  # type: ignore[method-assign]

    sent_messages: list[Message] = []

    async def mock_send(message: Message) -> None:
        sent_messages.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"content-type", b"application/json")],
    }

    async def mock_receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async with manager.run():
        # Create session
        await manager.handle_request(scope, mock_receive, mock_send)

        # Extract session ID
        session_id = None
        for msg in sent_messages:
            if msg["type"] == "http.response.start":
                for header_name, header_value in msg.get("headers", []):
                    if header_name.decode().lower() == MCP_SESSION_ID_HEADER.lower():
                        session_id = header_value.decode()
                        break
                if session_id:
                    break

        assert session_id is not None

        # Clear messages
        sent_messages.clear()

        # Make another request with same session
        scope_with_session = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [
                (b"content-type", b"application/json"),
                (MCP_SESSION_ID_HEADER.encode(), session_id.encode()),
            ],
        }

        # Track if we hit the roaming code path (should NOT)
        original_instances_count = len(manager._server_instances)  # type: ignore[attr-defined]

        await manager.handle_request(scope_with_session, mock_receive, mock_send)

        # Should still have same number of instances (fast path, no new transport created)
        assert len(manager._server_instances) == original_instances_count, (  # type: ignore[attr-defined]
            "Should use fast path for existing sessions"
        )


@pytest.mark.anyio
async def test_session_roaming_logs_correctly(caplog: Any):  # type: ignore[misc]
    """Test that session roaming logs the appropriate messages."""
    import logging

    caplog.set_level(logging.INFO)

    app = Server("test-roaming-logs")
    event_store = SimpleEventStore()

    # Create first manager and session
    manager1 = StreamableHTTPSessionManager(app=app, event_store=event_store)
    app.run = mock_app_run  # type: ignore[method-assign]

    sent_messages: list[Message] = []

    async def mock_send(message: Message) -> None:
        sent_messages.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"content-type", b"application/json")],
    }

    async def mock_receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async with manager1.run():
        await manager1.handle_request(scope, mock_receive, mock_send)

        # Extract session ID
        session_id = None
        for msg in sent_messages:
            if msg["type"] == "http.response.start":
                for header_name, header_value in msg.get("headers", []):
                    if header_name.decode().lower() == MCP_SESSION_ID_HEADER.lower():
                        session_id = header_value.decode()
                        break
                if session_id:
                    break

        assert session_id is not None

    # Clear logs
    caplog.clear()

    # Create second manager
    manager2 = StreamableHTTPSessionManager(app=app, event_store=event_store)
    app.run = mock_app_run  # type: ignore[method-assign]

    async with manager2.run():
        scope_with_session = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [
                (b"content-type", b"application/json"),
                (MCP_SESSION_ID_HEADER.encode(), session_id.encode()),
            ],
        }

        await manager2.handle_request(scope_with_session, mock_receive, mock_send)

        # Give time for logging
        await anyio.sleep(0.01)

        # Check logs for roaming messages
        log_messages = [record.message for record in caplog.records]

        assert any("roaming to this instance" in msg and "EventStore enables roaming" in msg for msg in log_messages), (
            "Should log session roaming"
        )

        assert any(f"Created transport for roaming session: {session_id}" in msg for msg in log_messages), (
            "Should log transport creation for roaming session"
        )
