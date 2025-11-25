"""Tests for TaskContext and helper functions."""

from unittest.mock import AsyncMock

import anyio
import pytest

from mcp.shared.experimental.tasks import (
    InMemoryTaskStore,
    TaskContext,
    create_task_state,
    run_task,
    task_execution,
)
from mcp.types import CallToolResult, TaskMetadata, TextContent


async def wait_for_terminal_status(store: InMemoryTaskStore, task_id: str, timeout: float = 5.0) -> None:
    """Wait for a task to reach terminal status (completed, failed, cancelled)."""
    terminal_statuses = {"completed", "failed", "cancelled"}
    with anyio.fail_after(timeout):
        while True:
            task = await store.get_task(task_id)
            if task and task.status in terminal_statuses:
                return
            await anyio.sleep(0)  # Yield to allow other tasks to run


# --- TaskContext tests ---


@pytest.mark.anyio
async def test_task_context_properties() -> None:
    """Test TaskContext basic properties."""
    store = InMemoryTaskStore()
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    ctx = TaskContext(task, store, session=None)

    assert ctx.task_id == task.taskId
    assert ctx.task.taskId == task.taskId
    assert ctx.task.status == "working"
    assert ctx.is_cancelled is False

    store.cleanup()


@pytest.mark.anyio
async def test_task_context_update_status() -> None:
    """Test TaskContext.update_status."""
    store = InMemoryTaskStore()
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    ctx = TaskContext(task, store, session=None)

    await ctx.update_status("Processing...", notify=False)

    assert ctx.task.statusMessage == "Processing..."
    retrieved = await store.get_task(task.taskId)
    assert retrieved is not None
    assert retrieved.statusMessage == "Processing..."

    store.cleanup()


@pytest.mark.anyio
async def test_task_context_update_status_multiple() -> None:
    """Test multiple status updates."""
    store = InMemoryTaskStore()
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    ctx = TaskContext(task, store, session=None)

    await ctx.update_status("Step 1...", notify=False)
    assert ctx.task.statusMessage == "Step 1..."

    await ctx.update_status("Step 2...", notify=False)
    assert ctx.task.statusMessage == "Step 2..."

    await ctx.update_status("Step 3...", notify=False)
    assert ctx.task.statusMessage == "Step 3..."

    store.cleanup()


@pytest.mark.anyio
async def test_task_context_complete() -> None:
    """Test TaskContext.complete."""
    store = InMemoryTaskStore()
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    ctx = TaskContext(task, store, session=None)

    result = CallToolResult(content=[TextContent(type="text", text="Done!")])
    await ctx.complete(result, notify=False)

    assert ctx.task.status == "completed"

    stored_result = await store.get_result(task.taskId)
    assert stored_result == result

    store.cleanup()


@pytest.mark.anyio
async def test_task_context_fail() -> None:
    """Test TaskContext.fail."""
    store = InMemoryTaskStore()
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    ctx = TaskContext(task, store, session=None)

    await ctx.fail("Something went wrong", notify=False)

    assert ctx.task.status == "failed"
    assert ctx.task.statusMessage == "Something went wrong"

    store.cleanup()


@pytest.mark.anyio
async def test_task_context_cancellation() -> None:
    """Test TaskContext cancellation flag."""
    store = InMemoryTaskStore()
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    ctx = TaskContext(task, store, session=None)

    assert ctx.is_cancelled is False

    ctx.request_cancellation()

    assert ctx.is_cancelled is True

    store.cleanup()


@pytest.mark.anyio
async def test_task_context_no_notification_without_session() -> None:
    """Test that notification doesn't fail when no session is provided."""
    store = InMemoryTaskStore()
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    ctx = TaskContext(task, store, session=None)

    # These should not raise even with notify=True (default)
    await ctx.update_status("Status update")
    await ctx.complete(CallToolResult(content=[TextContent(type="text", text="Done")]))

    store.cleanup()


# --- create_task_state helper tests ---


def test_create_task_state_generates_id() -> None:
    """Test create_task_state generates a task ID."""
    metadata = TaskMetadata(ttl=60000)
    task = create_task_state(metadata)

    assert task.taskId is not None
    assert len(task.taskId) > 0
    assert task.status == "working"
    assert task.ttl == 60000
    assert task.pollInterval == 500  # Default poll interval


def test_create_task_state_uses_provided_id() -> None:
    """Test create_task_state uses provided task ID."""
    metadata = TaskMetadata(ttl=60000)
    task = create_task_state(metadata, task_id="my-task-id")

    assert task.taskId == "my-task-id"


def test_create_task_state_null_ttl() -> None:
    """Test create_task_state with null TTL."""
    metadata = TaskMetadata(ttl=None)
    task = create_task_state(metadata)

    assert task.ttl is None
    assert task.status == "working"


def test_create_task_state_has_created_at() -> None:
    """Test create_task_state sets createdAt timestamp."""
    metadata = TaskMetadata(ttl=60000)
    task = create_task_state(metadata)

    assert task.createdAt is not None


# --- TaskContext notification tests (with mock session) ---


@pytest.mark.anyio
async def test_task_context_sends_notification_on_fail() -> None:
    """Test TaskContext.fail sends notification when session is provided."""
    store = InMemoryTaskStore()
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))

    # Create a mock session with send_notification method
    mock_session = AsyncMock()

    ctx = TaskContext(task, store, session=mock_session)

    # Fail with notification enabled (default)
    await ctx.fail("Test error")

    # Verify notification was sent
    assert mock_session.send_notification.called
    call_args = mock_session.send_notification.call_args[0][0]
    # The notification is wrapped in ServerNotification
    assert call_args.root.params.taskId == task.taskId
    assert call_args.root.params.status == "failed"
    assert call_args.root.params.statusMessage == "Test error"

    store.cleanup()


@pytest.mark.anyio
async def test_task_context_sends_notification_on_update_status() -> None:
    """Test TaskContext.update_status sends notification when session is provided."""
    store = InMemoryTaskStore()
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))

    mock_session = AsyncMock()
    ctx = TaskContext(task, store, session=mock_session)

    # Update status with notification enabled (default)
    await ctx.update_status("Processing...")

    # Verify notification was sent
    assert mock_session.send_notification.called
    call_args = mock_session.send_notification.call_args[0][0]
    assert call_args.root.params.taskId == task.taskId
    assert call_args.root.params.status == "working"
    assert call_args.root.params.statusMessage == "Processing..."

    store.cleanup()


@pytest.mark.anyio
async def test_task_context_sends_notification_on_complete() -> None:
    """Test TaskContext.complete sends notification when session is provided."""
    store = InMemoryTaskStore()
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))

    mock_session = AsyncMock()
    ctx = TaskContext(task, store, session=mock_session)

    result = CallToolResult(content=[TextContent(type="text", text="Done!")])
    await ctx.complete(result)

    # Verify notification was sent
    assert mock_session.send_notification.called
    call_args = mock_session.send_notification.call_args[0][0]
    assert call_args.root.params.taskId == task.taskId
    assert call_args.root.params.status == "completed"

    store.cleanup()


# --- task_execution context manager tests ---


@pytest.mark.anyio
async def test_task_execution_raises_on_nonexistent_task() -> None:
    """Test task_execution raises ValueError when task doesn't exist."""
    store = InMemoryTaskStore()

    with pytest.raises(ValueError, match="Task nonexistent-id not found"):
        async with task_execution("nonexistent-id", store):
            pass

    store.cleanup()


@pytest.mark.anyio
async def test_task_execution_auto_fails_on_exception() -> None:
    """Test task_execution automatically fails task on unhandled exception."""
    store = InMemoryTaskStore()
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))

    # task_execution suppresses exceptions and auto-fails the task
    async with task_execution(task.taskId, store) as ctx:
        await ctx.update_status("Starting...", notify=False)
        raise RuntimeError("Simulated error")

    # Execution reaches here because exception is suppressed
    # Task should be in failed state
    failed_task = await store.get_task(task.taskId)
    assert failed_task is not None
    assert failed_task.status == "failed"
    assert failed_task.statusMessage == "Simulated error"

    store.cleanup()


@pytest.mark.anyio
async def test_task_execution_doesnt_fail_if_already_terminal() -> None:
    """Test task_execution doesn't re-fail if task is already in terminal state."""
    store = InMemoryTaskStore()
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))

    # Complete the task first, then raise exception
    async with task_execution(task.taskId, store) as ctx:
        result = CallToolResult(content=[TextContent(type="text", text="Done")])
        await ctx.complete(result, notify=False)
        # Now raise - but task is already completed
        raise RuntimeError("Post-completion error")

    # Task should remain completed (not failed)
    completed_task = await store.get_task(task.taskId)
    assert completed_task is not None
    assert completed_task.status == "completed"

    store.cleanup()


# --- run_task helper function tests ---


@pytest.mark.anyio
async def test_run_task_successful_completion() -> None:
    """Test run_task successfully completes work and sets result."""
    store = InMemoryTaskStore()

    async def work(ctx: TaskContext) -> CallToolResult:
        await ctx.update_status("Working...", notify=False)
        return CallToolResult(content=[TextContent(type="text", text="Success!")])

    async with anyio.create_task_group() as tg:
        result, _ = await run_task(
            tg,
            store,
            TaskMetadata(ttl=60000),
            work,
        )

        # Result should be CreateTaskResult with initial working state
        assert result.task.status == "working"
        task_id = result.task.taskId

        # Wait for work to complete
        await wait_for_terminal_status(store, task_id)

        # Check task is completed
        task = await store.get_task(task_id)
        assert task is not None
        assert task.status == "completed"

        # Check result is stored
        stored_result = await store.get_result(task_id)
        assert stored_result is not None
        assert isinstance(stored_result, CallToolResult)
        assert stored_result.content[0].text == "Success!"  # type: ignore[union-attr]

    store.cleanup()


@pytest.mark.anyio
async def test_run_task_auto_fails_on_exception() -> None:
    """Test run_task automatically fails task when work raises exception."""
    store = InMemoryTaskStore()

    async def failing_work(ctx: TaskContext) -> CallToolResult:
        await ctx.update_status("About to fail...", notify=False)
        raise RuntimeError("Work failed!")

    async with anyio.create_task_group() as tg:
        result, _ = await run_task(
            tg,
            store,
            TaskMetadata(ttl=60000),
            failing_work,
        )

        task_id = result.task.taskId

        # Wait for work to complete (fail)
        await wait_for_terminal_status(store, task_id)

        # Check task is failed
        task = await store.get_task(task_id)
        assert task is not None
        assert task.status == "failed"
        assert task.statusMessage == "Work failed!"

    store.cleanup()


@pytest.mark.anyio
async def test_run_task_with_custom_task_id() -> None:
    """Test run_task with custom task_id."""
    store = InMemoryTaskStore()

    async def work(ctx: TaskContext) -> CallToolResult:
        return CallToolResult(content=[TextContent(type="text", text="Done")])

    async with anyio.create_task_group() as tg:
        result, _ = await run_task(
            tg,
            store,
            TaskMetadata(ttl=60000),
            work,
            task_id="my-custom-task-id",
        )

        assert result.task.taskId == "my-custom-task-id"

        # Wait for work to complete
        await wait_for_terminal_status(store, "my-custom-task-id")

        task = await store.get_task("my-custom-task-id")
        assert task is not None
        assert task.status == "completed"

    store.cleanup()


@pytest.mark.anyio
async def test_run_task_doesnt_fail_if_already_terminal() -> None:
    """Test run_task doesn't re-fail if task already reached terminal state."""
    store = InMemoryTaskStore()

    async def work_that_cancels_then_fails(ctx: TaskContext) -> CallToolResult:
        # Manually mark as cancelled, then raise
        await store.update_task(ctx.task_id, status="cancelled")
        # Refresh ctx's task state
        ctx._task = await store.get_task(ctx.task_id)  # type: ignore[assignment]
        raise RuntimeError("This shouldn't change the status")

    async with anyio.create_task_group() as tg:
        result, _ = await run_task(
            tg,
            store,
            TaskMetadata(ttl=60000),
            work_that_cancels_then_fails,
        )

        task_id = result.task.taskId

        # Wait for work to complete
        await wait_for_terminal_status(store, task_id)

        # Task should remain cancelled (not changed to failed)
        task = await store.get_task(task_id)
        assert task is not None
        assert task.status == "cancelled"

    store.cleanup()


@pytest.mark.anyio
async def test_run_task_doesnt_complete_if_already_terminal() -> None:
    """Test run_task doesn't complete if task already reached terminal state."""
    store = InMemoryTaskStore()

    async def work_that_completes_after_cancel(ctx: TaskContext) -> CallToolResult:
        # Manually mark as cancelled before returning result
        await store.update_task(ctx.task_id, status="cancelled")
        # Refresh ctx's task state
        ctx._task = await store.get_task(ctx.task_id)  # type: ignore[assignment]
        # Return a result, but task shouldn't be marked completed
        return CallToolResult(content=[TextContent(type="text", text="Done")])

    async with anyio.create_task_group() as tg:
        result, _ = await run_task(
            tg,
            store,
            TaskMetadata(ttl=60000),
            work_that_completes_after_cancel,
        )

        task_id = result.task.taskId

        # Wait for work to complete
        await wait_for_terminal_status(store, task_id)

        # Task should remain cancelled (not changed to completed)
        task = await store.get_task(task_id)
        assert task is not None
        assert task.status == "cancelled"

    store.cleanup()
