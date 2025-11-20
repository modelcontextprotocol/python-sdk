"""Tests for TaskContext and helper functions."""

import pytest

from mcp.shared.experimental.tasks import (
    InMemoryTaskStore,
    TaskContext,
    create_task_state,
)
from mcp.types import CallToolResult, TaskMetadata, TextContent

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
