"""Tests for ServerTaskContext."""

import asyncio
from unittest.mock import AsyncMock, Mock

import anyio
import pytest

from mcp.server.experimental.task_context import ServerTaskContext
from mcp.server.experimental.task_result_handler import TaskResultHandler
from mcp.shared.exceptions import McpError
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.shared.experimental.tasks.message_queue import InMemoryTaskMessageQueue
from mcp.types import (
    CallToolResult,
    ClientCapabilities,
    ClientTasksCapability,
    ClientTasksRequestsCapability,
    Implementation,
    InitializeRequestParams,
    JSONRPCRequest,
    SamplingMessage,
    TaskMetadata,
    TasksCreateElicitationCapability,
    TasksCreateMessageCapability,
    TasksElicitationCapability,
    TasksSamplingCapability,
    TextContent,
)


@pytest.mark.anyio
async def test_server_task_context_properties() -> None:
    """Test ServerTaskContext property accessors."""
    store = InMemoryTaskStore()
    mock_session = Mock()
    queue = InMemoryTaskMessageQueue()
    task = await store.create_task(TaskMetadata(ttl=60000), task_id="test-123")

    ctx = ServerTaskContext(
        task=task,
        store=store,
        session=mock_session,
        queue=queue,
    )

    assert ctx.task_id == "test-123"
    assert ctx.task.taskId == "test-123"
    assert ctx.is_cancelled is False

    store.cleanup()


@pytest.mark.anyio
async def test_server_task_context_request_cancellation() -> None:
    """Test ServerTaskContext.request_cancellation()."""
    store = InMemoryTaskStore()
    mock_session = Mock()
    queue = InMemoryTaskMessageQueue()
    task = await store.create_task(TaskMetadata(ttl=60000))

    ctx = ServerTaskContext(
        task=task,
        store=store,
        session=mock_session,
        queue=queue,
    )

    assert ctx.is_cancelled is False
    ctx.request_cancellation()
    assert ctx.is_cancelled is True

    store.cleanup()


@pytest.mark.anyio
async def test_server_task_context_update_status_with_notify() -> None:
    """Test update_status sends notification when notify=True."""
    store = InMemoryTaskStore()
    mock_session = Mock()
    mock_session.send_notification = AsyncMock()
    queue = InMemoryTaskMessageQueue()
    task = await store.create_task(TaskMetadata(ttl=60000))

    ctx = ServerTaskContext(
        task=task,
        store=store,
        session=mock_session,
        queue=queue,
    )

    await ctx.update_status("Working...", notify=True)

    mock_session.send_notification.assert_called_once()
    store.cleanup()


@pytest.mark.anyio
async def test_server_task_context_update_status_without_notify() -> None:
    """Test update_status skips notification when notify=False."""
    store = InMemoryTaskStore()
    mock_session = Mock()
    mock_session.send_notification = AsyncMock()
    queue = InMemoryTaskMessageQueue()
    task = await store.create_task(TaskMetadata(ttl=60000))

    ctx = ServerTaskContext(
        task=task,
        store=store,
        session=mock_session,
        queue=queue,
    )

    await ctx.update_status("Working...", notify=False)

    mock_session.send_notification.assert_not_called()
    store.cleanup()


@pytest.mark.anyio
async def test_server_task_context_complete_with_notify() -> None:
    """Test complete sends notification when notify=True."""
    store = InMemoryTaskStore()
    mock_session = Mock()
    mock_session.send_notification = AsyncMock()
    queue = InMemoryTaskMessageQueue()
    task = await store.create_task(TaskMetadata(ttl=60000))

    ctx = ServerTaskContext(
        task=task,
        store=store,
        session=mock_session,
        queue=queue,
    )

    result = CallToolResult(content=[TextContent(type="text", text="Done")])
    await ctx.complete(result, notify=True)

    mock_session.send_notification.assert_called_once()
    store.cleanup()


@pytest.mark.anyio
async def test_server_task_context_fail_with_notify() -> None:
    """Test fail sends notification when notify=True."""
    store = InMemoryTaskStore()
    mock_session = Mock()
    mock_session.send_notification = AsyncMock()
    queue = InMemoryTaskMessageQueue()
    task = await store.create_task(TaskMetadata(ttl=60000))

    ctx = ServerTaskContext(
        task=task,
        store=store,
        session=mock_session,
        queue=queue,
    )

    await ctx.fail("Something went wrong", notify=True)

    mock_session.send_notification.assert_called_once()
    store.cleanup()


@pytest.mark.anyio
async def test_elicit_raises_when_client_lacks_capability() -> None:
    """Test that elicit() raises McpError when client doesn't support elicitation."""
    store = InMemoryTaskStore()
    mock_session = Mock()
    mock_session.check_client_capability = Mock(return_value=False)
    queue = InMemoryTaskMessageQueue()
    handler = TaskResultHandler(store, queue)
    task = await store.create_task(TaskMetadata(ttl=60000))

    ctx = ServerTaskContext(
        task=task,
        store=store,
        session=mock_session,
        queue=queue,
        handler=handler,
    )

    with pytest.raises(McpError) as exc_info:
        await ctx.elicit(message="Test?", requestedSchema={"type": "object"})

    assert "elicitation capability" in exc_info.value.error.message
    mock_session.check_client_capability.assert_called_once()
    store.cleanup()


@pytest.mark.anyio
async def test_create_message_raises_when_client_lacks_capability() -> None:
    """Test that create_message() raises McpError when client doesn't support sampling."""
    store = InMemoryTaskStore()
    mock_session = Mock()
    mock_session.check_client_capability = Mock(return_value=False)
    queue = InMemoryTaskMessageQueue()
    handler = TaskResultHandler(store, queue)
    task = await store.create_task(TaskMetadata(ttl=60000))

    ctx = ServerTaskContext(
        task=task,
        store=store,
        session=mock_session,
        queue=queue,
        handler=handler,
    )

    with pytest.raises(McpError) as exc_info:
        await ctx.create_message(messages=[], max_tokens=100)

    assert "sampling capability" in exc_info.value.error.message
    mock_session.check_client_capability.assert_called_once()
    store.cleanup()


@pytest.mark.anyio
async def test_elicit_raises_without_handler() -> None:
    """Test that elicit() raises when handler is not provided."""
    store = InMemoryTaskStore()
    mock_session = Mock()
    mock_session.check_client_capability = Mock(return_value=True)
    queue = InMemoryTaskMessageQueue()
    task = await store.create_task(TaskMetadata(ttl=60000))

    ctx = ServerTaskContext(
        task=task,
        store=store,
        session=mock_session,
        queue=queue,
        handler=None,
    )

    with pytest.raises(RuntimeError, match="handler is required"):
        await ctx.elicit(message="Test?", requestedSchema={"type": "object"})

    store.cleanup()


@pytest.mark.anyio
async def test_elicit_url_raises_without_handler() -> None:
    """Test that elicit_url() raises when handler is not provided."""
    store = InMemoryTaskStore()
    mock_session = Mock()
    mock_session.check_client_capability = Mock(return_value=True)
    queue = InMemoryTaskMessageQueue()
    task = await store.create_task(TaskMetadata(ttl=60000))

    ctx = ServerTaskContext(
        task=task,
        store=store,
        session=mock_session,
        queue=queue,
        handler=None,
    )

    with pytest.raises(RuntimeError, match="handler is required for elicit_url"):
        await ctx.elicit_url(
            message="Please authorize",
            url="https://example.com/oauth",
            elicitation_id="oauth-123",
        )

    store.cleanup()


@pytest.mark.anyio
async def test_create_message_raises_without_handler() -> None:
    """Test that create_message() raises when handler is not provided."""
    store = InMemoryTaskStore()
    mock_session = Mock()
    mock_session.check_client_capability = Mock(return_value=True)
    queue = InMemoryTaskMessageQueue()
    task = await store.create_task(TaskMetadata(ttl=60000))

    ctx = ServerTaskContext(
        task=task,
        store=store,
        session=mock_session,
        queue=queue,
        handler=None,
    )

    with pytest.raises(RuntimeError, match="handler is required"):
        await ctx.create_message(messages=[], max_tokens=100)

    store.cleanup()


@pytest.mark.anyio
async def test_elicit_queues_request_and_waits_for_response() -> None:
    """Test that elicit() queues request and waits for response."""
    store = InMemoryTaskStore()
    queue = InMemoryTaskMessageQueue()
    handler = TaskResultHandler(store, queue)
    task = await store.create_task(TaskMetadata(ttl=60000))

    mock_session = Mock()
    mock_session.check_client_capability = Mock(return_value=True)
    mock_session._build_elicit_form_request = Mock(
        return_value=JSONRPCRequest(
            jsonrpc="2.0",
            id="test-req-1",
            method="elicitation/create",
            params={"message": "Test?", "_meta": {}},
        )
    )

    ctx = ServerTaskContext(
        task=task,
        store=store,
        session=mock_session,
        queue=queue,
        handler=handler,
    )

    elicit_result = None

    async def run_elicit() -> None:
        nonlocal elicit_result
        elicit_result = await ctx.elicit(
            message="Test?",
            requestedSchema={"type": "object"},
        )

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_elicit)

        # Wait for request to be queued
        await queue.wait_for_message(task.taskId)

        # Verify task is in input_required status
        updated_task = await store.get_task(task.taskId)
        assert updated_task is not None
        assert updated_task.status == "input_required"

        # Dequeue and simulate response
        msg = await queue.dequeue(task.taskId)
        assert msg is not None
        assert msg.resolver is not None

        # Resolve with mock elicitation response
        msg.resolver.set_result({"action": "accept", "content": {"name": "Alice"}})

    # Verify result
    assert elicit_result is not None
    assert elicit_result.action == "accept"
    assert elicit_result.content == {"name": "Alice"}

    # Verify task is back to working
    final_task = await store.get_task(task.taskId)
    assert final_task is not None
    assert final_task.status == "working"

    store.cleanup()


@pytest.mark.anyio
async def test_elicit_url_queues_request_and_waits_for_response() -> None:
    """Test that elicit_url() queues request and waits for response."""
    store = InMemoryTaskStore()
    queue = InMemoryTaskMessageQueue()
    handler = TaskResultHandler(store, queue)
    task = await store.create_task(TaskMetadata(ttl=60000))

    mock_session = Mock()
    mock_session.check_client_capability = Mock(return_value=True)
    mock_session._build_elicit_url_request = Mock(
        return_value=JSONRPCRequest(
            jsonrpc="2.0",
            id="test-url-req-1",
            method="elicitation/create",
            params={"message": "Authorize", "url": "https://example.com", "elicitationId": "123", "mode": "url"},
        )
    )

    ctx = ServerTaskContext(
        task=task,
        store=store,
        session=mock_session,
        queue=queue,
        handler=handler,
    )

    elicit_result = None

    async def run_elicit_url() -> None:
        nonlocal elicit_result
        elicit_result = await ctx.elicit_url(
            message="Authorize",
            url="https://example.com/oauth",
            elicitation_id="oauth-123",
        )

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_elicit_url)

        # Wait for request to be queued
        await queue.wait_for_message(task.taskId)

        # Verify task is in input_required status
        updated_task = await store.get_task(task.taskId)
        assert updated_task is not None
        assert updated_task.status == "input_required"

        # Dequeue and simulate response
        msg = await queue.dequeue(task.taskId)
        assert msg is not None
        assert msg.resolver is not None

        # Resolve with mock elicitation response (URL mode just returns action)
        msg.resolver.set_result({"action": "accept"})

    # Verify result
    assert elicit_result is not None
    assert elicit_result.action == "accept"

    # Verify task is back to working
    final_task = await store.get_task(task.taskId)
    assert final_task is not None
    assert final_task.status == "working"

    store.cleanup()


@pytest.mark.anyio
async def test_create_message_queues_request_and_waits_for_response() -> None:
    """Test that create_message() queues request and waits for response."""
    store = InMemoryTaskStore()
    queue = InMemoryTaskMessageQueue()
    handler = TaskResultHandler(store, queue)
    task = await store.create_task(TaskMetadata(ttl=60000))

    mock_session = Mock()
    mock_session.check_client_capability = Mock(return_value=True)
    mock_session._build_create_message_request = Mock(
        return_value=JSONRPCRequest(
            jsonrpc="2.0",
            id="test-req-2",
            method="sampling/createMessage",
            params={"messages": [], "maxTokens": 100, "_meta": {}},
        )
    )

    ctx = ServerTaskContext(
        task=task,
        store=store,
        session=mock_session,
        queue=queue,
        handler=handler,
    )

    sampling_result = None

    async def run_sampling() -> None:
        nonlocal sampling_result
        sampling_result = await ctx.create_message(
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text="Hello"))],
            max_tokens=100,
        )

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_sampling)

        # Wait for request to be queued
        await queue.wait_for_message(task.taskId)

        # Verify task is in input_required status
        updated_task = await store.get_task(task.taskId)
        assert updated_task is not None
        assert updated_task.status == "input_required"

        # Dequeue and simulate response
        msg = await queue.dequeue(task.taskId)
        assert msg is not None
        assert msg.resolver is not None

        # Resolve with mock sampling response
        msg.resolver.set_result(
            {
                "role": "assistant",
                "content": {"type": "text", "text": "Hello back!"},
                "model": "test-model",
                "stopReason": "endTurn",
            }
        )

    # Verify result
    assert sampling_result is not None
    assert sampling_result.role == "assistant"
    assert sampling_result.model == "test-model"

    # Verify task is back to working
    final_task = await store.get_task(task.taskId)
    assert final_task is not None
    assert final_task.status == "working"

    store.cleanup()


@pytest.mark.anyio
async def test_elicit_restores_status_on_cancellation() -> None:
    """Test that elicit() restores task status to working when cancelled."""
    store = InMemoryTaskStore()
    queue = InMemoryTaskMessageQueue()
    handler = TaskResultHandler(store, queue)
    task = await store.create_task(TaskMetadata(ttl=60000))

    mock_session = Mock()
    mock_session.check_client_capability = Mock(return_value=True)
    mock_session._build_elicit_form_request = Mock(
        return_value=JSONRPCRequest(
            jsonrpc="2.0",
            id="test-req-cancel",
            method="elicitation/create",
            params={"message": "Test?", "_meta": {}},
        )
    )

    ctx = ServerTaskContext(
        task=task,
        store=store,
        session=mock_session,
        queue=queue,
        handler=handler,
    )

    cancelled_error_raised = False

    async with anyio.create_task_group() as tg:

        async def do_elicit() -> None:
            nonlocal cancelled_error_raised
            try:
                await ctx.elicit(
                    message="Test?",
                    requestedSchema={"type": "object"},
                )
            except anyio.get_cancelled_exc_class():
                cancelled_error_raised = True
                # Don't re-raise - let the test continue

        tg.start_soon(do_elicit)

        # Wait for request to be queued
        await queue.wait_for_message(task.taskId)

        # Verify task is in input_required status
        updated_task = await store.get_task(task.taskId)
        assert updated_task is not None
        assert updated_task.status == "input_required"

        # Get the queued message and set cancellation exception on its resolver
        msg = await queue.dequeue(task.taskId)
        assert msg is not None
        assert msg.resolver is not None

        # Trigger cancellation by setting exception (use asyncio.CancelledError directly)
        msg.resolver.set_exception(asyncio.CancelledError())

    # Verify task is back to working after cancellation
    final_task = await store.get_task(task.taskId)
    assert final_task is not None
    assert final_task.status == "working"
    assert cancelled_error_raised

    store.cleanup()


@pytest.mark.anyio
async def test_create_message_restores_status_on_cancellation() -> None:
    """Test that create_message() restores task status to working when cancelled."""
    store = InMemoryTaskStore()
    queue = InMemoryTaskMessageQueue()
    handler = TaskResultHandler(store, queue)
    task = await store.create_task(TaskMetadata(ttl=60000))

    mock_session = Mock()
    mock_session.check_client_capability = Mock(return_value=True)
    mock_session._build_create_message_request = Mock(
        return_value=JSONRPCRequest(
            jsonrpc="2.0",
            id="test-req-cancel-2",
            method="sampling/createMessage",
            params={"messages": [], "maxTokens": 100, "_meta": {}},
        )
    )

    ctx = ServerTaskContext(
        task=task,
        store=store,
        session=mock_session,
        queue=queue,
        handler=handler,
    )

    cancelled_error_raised = False

    async with anyio.create_task_group() as tg:

        async def do_sampling() -> None:
            nonlocal cancelled_error_raised
            try:
                await ctx.create_message(
                    messages=[SamplingMessage(role="user", content=TextContent(type="text", text="Hello"))],
                    max_tokens=100,
                )
            except anyio.get_cancelled_exc_class():
                cancelled_error_raised = True
                # Don't re-raise

        tg.start_soon(do_sampling)

        # Wait for request to be queued
        await queue.wait_for_message(task.taskId)

        # Verify task is in input_required status
        updated_task = await store.get_task(task.taskId)
        assert updated_task is not None
        assert updated_task.status == "input_required"

        # Get the queued message and set cancellation exception on its resolver
        msg = await queue.dequeue(task.taskId)
        assert msg is not None
        assert msg.resolver is not None

        # Trigger cancellation by setting exception (use asyncio.CancelledError directly)
        msg.resolver.set_exception(asyncio.CancelledError())

    # Verify task is back to working after cancellation
    final_task = await store.get_task(task.taskId)
    assert final_task is not None
    assert final_task.status == "working"
    assert cancelled_error_raised

    store.cleanup()


@pytest.mark.anyio
async def test_elicit_as_task_raises_without_handler() -> None:
    """Test that elicit_as_task() raises when handler is not provided."""
    store = InMemoryTaskStore()
    queue = InMemoryTaskMessageQueue()
    task = await store.create_task(TaskMetadata(ttl=60000))

    # Create mock session with proper client capabilities
    mock_session = Mock()
    mock_session.client_params = InitializeRequestParams(
        protocolVersion="2025-01-01",
        capabilities=ClientCapabilities(
            tasks=ClientTasksCapability(
                requests=ClientTasksRequestsCapability(
                    elicitation=TasksElicitationCapability(create=TasksCreateElicitationCapability())
                )
            )
        ),
        clientInfo=Implementation(name="test", version="1.0"),
    )

    ctx = ServerTaskContext(
        task=task,
        store=store,
        session=mock_session,
        queue=queue,
        handler=None,
    )

    with pytest.raises(RuntimeError, match="handler is required for elicit_as_task"):
        await ctx.elicit_as_task(message="Test?", requestedSchema={"type": "object"})

    store.cleanup()


@pytest.mark.anyio
async def test_create_message_as_task_raises_without_handler() -> None:
    """Test that create_message_as_task() raises when handler is not provided."""
    store = InMemoryTaskStore()
    queue = InMemoryTaskMessageQueue()
    task = await store.create_task(TaskMetadata(ttl=60000))

    # Create mock session with proper client capabilities
    mock_session = Mock()
    mock_session.client_params = InitializeRequestParams(
        protocolVersion="2025-01-01",
        capabilities=ClientCapabilities(
            tasks=ClientTasksCapability(
                requests=ClientTasksRequestsCapability(
                    sampling=TasksSamplingCapability(createMessage=TasksCreateMessageCapability())
                )
            )
        ),
        clientInfo=Implementation(name="test", version="1.0"),
    )

    ctx = ServerTaskContext(
        task=task,
        store=store,
        session=mock_session,
        queue=queue,
        handler=None,
    )

    with pytest.raises(RuntimeError, match="handler is required for create_message_as_task"):
        await ctx.create_message_as_task(
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text="Hello"))],
            max_tokens=100,
        )

    store.cleanup()
