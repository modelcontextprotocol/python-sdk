"""Tests for TaskResultHandler."""

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, Mock

import anyio
import pytest

from mcp.server.experimental.task_result_handler import TaskResultHandler
from mcp.shared.exceptions import McpError
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.shared.experimental.tasks.message_queue import InMemoryTaskMessageQueue, QueuedMessage
from mcp.shared.experimental.tasks.resolver import Resolver
from mcp.shared.message import SessionMessage
from mcp.types import (
    INVALID_REQUEST,
    CallToolResult,
    ErrorData,
    GetTaskPayloadRequest,
    GetTaskPayloadRequestParams,
    GetTaskPayloadResult,
    JSONRPCRequest,
    TaskMetadata,
    TextContent,
)


@pytest.fixture
async def store() -> AsyncIterator[InMemoryTaskStore]:
    """Provide a clean store for each test."""
    s = InMemoryTaskStore()
    yield s
    s.cleanup()


@pytest.fixture
def queue() -> InMemoryTaskMessageQueue:
    """Provide a clean queue for each test."""
    return InMemoryTaskMessageQueue()


@pytest.fixture
def handler(store: InMemoryTaskStore, queue: InMemoryTaskMessageQueue) -> TaskResultHandler:
    """Provide a handler for each test."""
    return TaskResultHandler(store, queue)


@pytest.mark.anyio
async def test_handle_returns_result_for_completed_task(
    store: InMemoryTaskStore, queue: InMemoryTaskMessageQueue, handler: TaskResultHandler
) -> None:
    """Test that handle() returns the stored result for a completed task."""
    task = await store.create_task(TaskMetadata(ttl=60000), task_id="test-task")
    result = CallToolResult(content=[TextContent(type="text", text="Done!")])
    await store.store_result(task.taskId, result)
    await store.update_task(task.taskId, status="completed")

    mock_session = Mock()
    mock_session.send_message = AsyncMock()

    request = GetTaskPayloadRequest(params=GetTaskPayloadRequestParams(taskId=task.taskId))
    response = await handler.handle(request, mock_session, "req-1")

    assert response is not None
    assert response.meta is not None
    assert "io.modelcontextprotocol/related-task" in response.meta


@pytest.mark.anyio
async def test_handle_raises_for_nonexistent_task(
    store: InMemoryTaskStore, queue: InMemoryTaskMessageQueue, handler: TaskResultHandler
) -> None:
    """Test that handle() raises McpError for nonexistent task."""
    mock_session = Mock()
    request = GetTaskPayloadRequest(params=GetTaskPayloadRequestParams(taskId="nonexistent"))

    with pytest.raises(McpError) as exc_info:
        await handler.handle(request, mock_session, "req-1")

    assert "not found" in exc_info.value.error.message


@pytest.mark.anyio
async def test_handle_returns_empty_result_when_no_result_stored(
    store: InMemoryTaskStore, queue: InMemoryTaskMessageQueue, handler: TaskResultHandler
) -> None:
    """Test that handle() returns minimal result when task completed without stored result."""
    task = await store.create_task(TaskMetadata(ttl=60000), task_id="test-task")
    await store.update_task(task.taskId, status="completed")

    mock_session = Mock()
    mock_session.send_message = AsyncMock()

    request = GetTaskPayloadRequest(params=GetTaskPayloadRequestParams(taskId=task.taskId))
    response = await handler.handle(request, mock_session, "req-1")

    assert response is not None
    assert response.meta is not None
    assert "io.modelcontextprotocol/related-task" in response.meta


@pytest.mark.anyio
async def test_handle_delivers_queued_messages(
    store: InMemoryTaskStore, queue: InMemoryTaskMessageQueue, handler: TaskResultHandler
) -> None:
    """Test that handle() delivers queued messages before returning."""
    task = await store.create_task(TaskMetadata(ttl=60000), task_id="test-task")

    queued_msg = QueuedMessage(
        type="notification",
        message=JSONRPCRequest(
            jsonrpc="2.0",
            id="notif-1",
            method="test/notification",
            params={},
        ),
    )
    await queue.enqueue(task.taskId, queued_msg)
    await store.update_task(task.taskId, status="completed")

    sent_messages: list[SessionMessage] = []

    async def track_send(msg: SessionMessage) -> None:
        sent_messages.append(msg)

    mock_session = Mock()
    mock_session.send_message = track_send

    request = GetTaskPayloadRequest(params=GetTaskPayloadRequestParams(taskId=task.taskId))
    await handler.handle(request, mock_session, "req-1")

    assert len(sent_messages) == 1


@pytest.mark.anyio
async def test_handle_waits_for_task_completion(
    store: InMemoryTaskStore, queue: InMemoryTaskMessageQueue, handler: TaskResultHandler
) -> None:
    """Test that handle() waits for task to complete before returning."""
    task = await store.create_task(TaskMetadata(ttl=60000), task_id="test-task")

    mock_session = Mock()
    mock_session.send_message = AsyncMock()

    request = GetTaskPayloadRequest(params=GetTaskPayloadRequestParams(taskId=task.taskId))
    result_holder: list[GetTaskPayloadResult | None] = [None]

    async def run_handle() -> None:
        result_holder[0] = await handler.handle(request, mock_session, "req-1")

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_handle)

        # Wait for handler to start waiting (event gets created when wait starts)
        while task.taskId not in store._update_events:
            await anyio.sleep(0)

        await store.store_result(task.taskId, CallToolResult(content=[TextContent(type="text", text="Done")]))
        await store.update_task(task.taskId, status="completed")

    assert result_holder[0] is not None


@pytest.mark.anyio
async def test_route_response_resolves_pending_request(
    store: InMemoryTaskStore, queue: InMemoryTaskMessageQueue, handler: TaskResultHandler
) -> None:
    """Test that route_response() resolves a pending request."""
    resolver: Resolver[dict[str, Any]] = Resolver()
    handler._pending_requests["req-123"] = resolver

    result = handler.route_response("req-123", {"status": "ok"})

    assert result is True
    assert resolver.done()
    assert await resolver.wait() == {"status": "ok"}


@pytest.mark.anyio
async def test_route_response_returns_false_for_unknown_request(
    store: InMemoryTaskStore, queue: InMemoryTaskMessageQueue, handler: TaskResultHandler
) -> None:
    """Test that route_response() returns False for unknown request ID."""
    result = handler.route_response("unknown-req", {"status": "ok"})
    assert result is False


@pytest.mark.anyio
async def test_route_response_returns_false_for_already_done_resolver(
    store: InMemoryTaskStore, queue: InMemoryTaskMessageQueue, handler: TaskResultHandler
) -> None:
    """Test that route_response() returns False if resolver already completed."""
    resolver: Resolver[dict[str, Any]] = Resolver()
    resolver.set_result({"already": "done"})
    handler._pending_requests["req-123"] = resolver

    result = handler.route_response("req-123", {"new": "data"})

    assert result is False


@pytest.mark.anyio
async def test_route_error_resolves_pending_request_with_exception(
    store: InMemoryTaskStore, queue: InMemoryTaskMessageQueue, handler: TaskResultHandler
) -> None:
    """Test that route_error() sets exception on pending request."""
    resolver: Resolver[dict[str, Any]] = Resolver()
    handler._pending_requests["req-123"] = resolver

    error = ErrorData(code=INVALID_REQUEST, message="Something went wrong")
    result = handler.route_error("req-123", error)

    assert result is True
    assert resolver.done()

    with pytest.raises(McpError) as exc_info:
        await resolver.wait()
    assert exc_info.value.error.message == "Something went wrong"


@pytest.mark.anyio
async def test_route_error_returns_false_for_unknown_request(
    store: InMemoryTaskStore, queue: InMemoryTaskMessageQueue, handler: TaskResultHandler
) -> None:
    """Test that route_error() returns False for unknown request ID."""
    error = ErrorData(code=INVALID_REQUEST, message="Error")
    result = handler.route_error("unknown-req", error)
    assert result is False


@pytest.mark.anyio
async def test_deliver_registers_resolver_for_request_messages(
    store: InMemoryTaskStore, queue: InMemoryTaskMessageQueue, handler: TaskResultHandler
) -> None:
    """Test that _deliver_queued_messages registers resolvers for request messages."""
    task = await store.create_task(TaskMetadata(ttl=60000), task_id="test-task")

    resolver: Resolver[dict[str, Any]] = Resolver()
    queued_msg = QueuedMessage(
        type="request",
        message=JSONRPCRequest(
            jsonrpc="2.0",
            id="inner-req-1",
            method="elicitation/create",
            params={},
        ),
        resolver=resolver,
        original_request_id="inner-req-1",
    )
    await queue.enqueue(task.taskId, queued_msg)

    mock_session = Mock()
    mock_session.send_message = AsyncMock()

    await handler._deliver_queued_messages(task.taskId, mock_session, "outer-req-1")

    assert "inner-req-1" in handler._pending_requests
    assert handler._pending_requests["inner-req-1"] is resolver


@pytest.mark.anyio
async def test_deliver_skips_resolver_registration_when_no_original_id(
    store: InMemoryTaskStore, queue: InMemoryTaskMessageQueue, handler: TaskResultHandler
) -> None:
    """Test that _deliver_queued_messages skips resolver registration when original_request_id is None."""
    task = await store.create_task(TaskMetadata(ttl=60000), task_id="test-task")

    resolver: Resolver[dict[str, Any]] = Resolver()
    queued_msg = QueuedMessage(
        type="request",
        message=JSONRPCRequest(
            jsonrpc="2.0",
            id="inner-req-1",
            method="elicitation/create",
            params={},
        ),
        resolver=resolver,
        original_request_id=None,  # No original request ID
    )
    await queue.enqueue(task.taskId, queued_msg)

    mock_session = Mock()
    mock_session.send_message = AsyncMock()

    await handler._deliver_queued_messages(task.taskId, mock_session, "outer-req-1")

    # Resolver should NOT be registered since original_request_id is None
    assert len(handler._pending_requests) == 0
    # But the message should still be sent
    mock_session.send_message.assert_called_once()


@pytest.mark.anyio
async def test_wait_for_task_update_handles_store_exception(
    store: InMemoryTaskStore, queue: InMemoryTaskMessageQueue, handler: TaskResultHandler
) -> None:
    """Test that _wait_for_task_update handles store exception gracefully."""
    task = await store.create_task(TaskMetadata(ttl=60000), task_id="test-task")

    # Make wait_for_update raise an exception
    async def failing_wait(task_id: str) -> None:
        raise RuntimeError("Store error")

    store.wait_for_update = failing_wait  # type: ignore[method-assign]

    # Queue a message to unblock the race via the queue path
    async def enqueue_later() -> None:
        # Wait for queue to start waiting (event gets created when wait starts)
        while task.taskId not in queue._events:
            await anyio.sleep(0)
        await queue.enqueue(
            task.taskId,
            QueuedMessage(
                type="notification",
                message=JSONRPCRequest(
                    jsonrpc="2.0",
                    id="notif-1",
                    method="test/notification",
                    params={},
                ),
            ),
        )

    async with anyio.create_task_group() as tg:
        tg.start_soon(enqueue_later)
        # This should complete via the queue path even though store raises
        await handler._wait_for_task_update(task.taskId)


@pytest.mark.anyio
async def test_wait_for_task_update_handles_queue_exception(
    store: InMemoryTaskStore, queue: InMemoryTaskMessageQueue, handler: TaskResultHandler
) -> None:
    """Test that _wait_for_task_update handles queue exception gracefully."""
    task = await store.create_task(TaskMetadata(ttl=60000), task_id="test-task")

    # Make wait_for_message raise an exception
    async def failing_wait(task_id: str) -> None:
        raise RuntimeError("Queue error")

    queue.wait_for_message = failing_wait  # type: ignore[method-assign]

    # Update the store to unblock the race via the store path
    async def update_later() -> None:
        # Wait for store to start waiting (event gets created when wait starts)
        while task.taskId not in store._update_events:
            await anyio.sleep(0)
        await store.update_task(task.taskId, status="completed")

    async with anyio.create_task_group() as tg:
        tg.start_soon(update_later)
        # This should complete via the store path even though queue raises
        await handler._wait_for_task_update(task.taskId)
