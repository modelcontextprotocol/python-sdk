"""Tests for TaskContext and helper functions."""

import pytest

from mcp.shared.experimental.tasks.context import TaskContext
from mcp.shared.experimental.tasks.helpers import create_task_state, task_execution
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.types import CallToolResult, TaskMetadata, TextContent


@pytest.mark.anyio
async def test_task_context_properties() -> None:
    """Test TaskContext basic properties."""
    store = InMemoryTaskStore()
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    ctx = TaskContext(task, store)

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
    ctx = TaskContext(task, store)

    await ctx.update_status("Processing step 1...")

    # Check status message was updated
    updated = await store.get_task(task.taskId)
    assert updated is not None
    assert updated.statusMessage == "Processing step 1..."

    store.cleanup()


@pytest.mark.anyio
async def test_task_context_complete() -> None:
    """Test TaskContext.complete."""
    store = InMemoryTaskStore()
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    ctx = TaskContext(task, store)

    result = CallToolResult(content=[TextContent(type="text", text="Done!")])
    await ctx.complete(result)

    # Check task status
    updated = await store.get_task(task.taskId)
    assert updated is not None
    assert updated.status == "completed"

    # Check result is stored
    stored_result = await store.get_result(task.taskId)
    assert stored_result is not None

    store.cleanup()


@pytest.mark.anyio
async def test_task_context_fail() -> None:
    """Test TaskContext.fail."""
    store = InMemoryTaskStore()
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    ctx = TaskContext(task, store)

    await ctx.fail("Something went wrong!")

    # Check task status
    updated = await store.get_task(task.taskId)
    assert updated is not None
    assert updated.status == "failed"
    assert updated.statusMessage == "Something went wrong!"

    store.cleanup()


@pytest.mark.anyio
async def test_task_context_cancellation() -> None:
    """Test TaskContext cancellation request."""
    store = InMemoryTaskStore()
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    ctx = TaskContext(task, store)

    assert ctx.is_cancelled is False

    ctx.request_cancellation()

    assert ctx.is_cancelled is True

    store.cleanup()


def test_create_task_state_generates_id() -> None:
    """create_task_state generates a unique task ID when none provided."""
    task1 = create_task_state(TaskMetadata(ttl=60000))
    task2 = create_task_state(TaskMetadata(ttl=60000))

    assert task1.taskId != task2.taskId


def test_create_task_state_uses_provided_id() -> None:
    """create_task_state uses the provided task ID."""
    task = create_task_state(TaskMetadata(ttl=60000), task_id="my-task-123")
    assert task.taskId == "my-task-123"


def test_create_task_state_null_ttl() -> None:
    """create_task_state handles null TTL."""
    task = create_task_state(TaskMetadata(ttl=None))
    assert task.ttl is None


def test_create_task_state_has_created_at() -> None:
    """create_task_state sets createdAt timestamp."""
    task = create_task_state(TaskMetadata(ttl=60000))
    assert task.createdAt is not None


@pytest.mark.anyio
async def test_task_execution_provides_context() -> None:
    """task_execution provides a TaskContext for the task."""
    store = InMemoryTaskStore()
    await store.create_task(TaskMetadata(ttl=60000), task_id="exec-test-1")

    async with task_execution("exec-test-1", store) as ctx:
        assert ctx.task_id == "exec-test-1"
        assert ctx.task.status == "working"

    store.cleanup()


@pytest.mark.anyio
async def test_task_execution_auto_fails_on_exception() -> None:
    """task_execution automatically fails task on unhandled exception."""
    store = InMemoryTaskStore()
    await store.create_task(TaskMetadata(ttl=60000), task_id="exec-fail-1")

    async with task_execution("exec-fail-1", store):
        raise RuntimeError("Oops!")

    # Task should be failed
    failed_task = await store.get_task("exec-fail-1")
    assert failed_task is not None
    assert failed_task.status == "failed"
    assert "Oops!" in (failed_task.statusMessage or "")

    store.cleanup()


@pytest.mark.anyio
async def test_task_execution_doesnt_fail_if_already_terminal() -> None:
    """task_execution doesn't re-fail if task already terminal."""
    store = InMemoryTaskStore()
    await store.create_task(TaskMetadata(ttl=60000), task_id="exec-term-1")

    async with task_execution("exec-term-1", store) as ctx:
        # Complete the task first
        await ctx.complete(CallToolResult(content=[TextContent(type="text", text="Done")]))
        # Then raise - shouldn't change status
        raise RuntimeError("This shouldn't matter")

    # Task should remain completed
    final_task = await store.get_task("exec-term-1")
    assert final_task is not None
    assert final_task.status == "completed"

    store.cleanup()


@pytest.mark.anyio
async def test_task_execution_not_found() -> None:
    """task_execution raises ValueError for non-existent task."""
    store = InMemoryTaskStore()

    with pytest.raises(ValueError, match="not found"):
        async with task_execution("nonexistent", store):
            ...
