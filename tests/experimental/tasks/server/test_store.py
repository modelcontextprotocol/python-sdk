"""Tests for InMemoryTaskStore."""

from datetime import datetime, timedelta, timezone

import pytest

from mcp.shared.exceptions import McpError
from mcp.shared.experimental.tasks.helpers import cancel_task
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.types import INVALID_PARAMS, CallToolResult, TaskMetadata, TextContent


@pytest.mark.anyio
async def test_create_and_get() -> None:
    """Test InMemoryTaskStore create and get operations."""
    store = InMemoryTaskStore()

    task = await store.create_task(metadata=TaskMetadata(ttl=60000))

    assert task.taskId is not None
    assert task.status == "working"
    assert task.ttl == 60000

    retrieved = await store.get_task(task.taskId)
    assert retrieved is not None
    assert retrieved.taskId == task.taskId
    assert retrieved.status == "working"

    store.cleanup()


@pytest.mark.anyio
async def test_create_with_custom_id() -> None:
    """Test InMemoryTaskStore create with custom task ID."""
    store = InMemoryTaskStore()

    task = await store.create_task(
        metadata=TaskMetadata(ttl=60000),
        task_id="my-custom-id",
    )

    assert task.taskId == "my-custom-id"
    assert task.status == "working"

    retrieved = await store.get_task("my-custom-id")
    assert retrieved is not None
    assert retrieved.taskId == "my-custom-id"

    store.cleanup()


@pytest.mark.anyio
async def test_create_duplicate_id_raises() -> None:
    """Test that creating a task with duplicate ID raises."""
    store = InMemoryTaskStore()

    await store.create_task(metadata=TaskMetadata(ttl=60000), task_id="duplicate")

    with pytest.raises(ValueError, match="already exists"):
        await store.create_task(metadata=TaskMetadata(ttl=60000), task_id="duplicate")

    store.cleanup()


@pytest.mark.anyio
async def test_get_nonexistent_returns_none() -> None:
    """Test that getting a nonexistent task returns None."""
    store = InMemoryTaskStore()

    retrieved = await store.get_task("nonexistent")
    assert retrieved is None

    store.cleanup()


@pytest.mark.anyio
async def test_update_status() -> None:
    """Test InMemoryTaskStore status updates."""
    store = InMemoryTaskStore()

    task = await store.create_task(metadata=TaskMetadata(ttl=60000))

    updated = await store.update_task(task.taskId, status="completed", status_message="All done!")

    assert updated.status == "completed"
    assert updated.statusMessage == "All done!"

    retrieved = await store.get_task(task.taskId)
    assert retrieved is not None
    assert retrieved.status == "completed"
    assert retrieved.statusMessage == "All done!"

    store.cleanup()


@pytest.mark.anyio
async def test_update_nonexistent_raises() -> None:
    """Test that updating a nonexistent task raises."""
    store = InMemoryTaskStore()

    with pytest.raises(ValueError, match="not found"):
        await store.update_task("nonexistent", status="completed")

    store.cleanup()


@pytest.mark.anyio
async def test_store_and_get_result() -> None:
    """Test InMemoryTaskStore result storage and retrieval."""
    store = InMemoryTaskStore()

    task = await store.create_task(metadata=TaskMetadata(ttl=60000))

    # Store result
    result = CallToolResult(content=[TextContent(type="text", text="Result data")])
    await store.store_result(task.taskId, result)

    # Retrieve result
    retrieved_result = await store.get_result(task.taskId)
    assert retrieved_result == result

    store.cleanup()


@pytest.mark.anyio
async def test_get_result_nonexistent_returns_none() -> None:
    """Test that getting result for nonexistent task returns None."""
    store = InMemoryTaskStore()

    result = await store.get_result("nonexistent")
    assert result is None

    store.cleanup()


@pytest.mark.anyio
async def test_get_result_no_result_returns_none() -> None:
    """Test that getting result when none stored returns None."""
    store = InMemoryTaskStore()

    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    result = await store.get_result(task.taskId)
    assert result is None

    store.cleanup()


@pytest.mark.anyio
async def test_list_tasks() -> None:
    """Test InMemoryTaskStore list operation."""
    store = InMemoryTaskStore()

    # Create multiple tasks
    for _ in range(3):
        await store.create_task(metadata=TaskMetadata(ttl=60000))

    tasks, next_cursor = await store.list_tasks()
    assert len(tasks) == 3
    assert next_cursor is None  # Less than page size

    store.cleanup()


@pytest.mark.anyio
async def test_list_tasks_pagination() -> None:
    """Test InMemoryTaskStore pagination."""
    store = InMemoryTaskStore(page_size=2)

    # Create 5 tasks
    for _ in range(5):
        await store.create_task(metadata=TaskMetadata(ttl=60000))

    # First page
    tasks, next_cursor = await store.list_tasks()
    assert len(tasks) == 2
    assert next_cursor is not None

    # Second page
    tasks, next_cursor = await store.list_tasks(cursor=next_cursor)
    assert len(tasks) == 2
    assert next_cursor is not None

    # Third page (last)
    tasks, next_cursor = await store.list_tasks(cursor=next_cursor)
    assert len(tasks) == 1
    assert next_cursor is None

    store.cleanup()


@pytest.mark.anyio
async def test_list_tasks_invalid_cursor() -> None:
    """Test that invalid cursor raises."""
    store = InMemoryTaskStore()

    await store.create_task(metadata=TaskMetadata(ttl=60000))

    with pytest.raises(ValueError, match="Invalid cursor"):
        await store.list_tasks(cursor="invalid-cursor")

    store.cleanup()


@pytest.mark.anyio
async def test_delete_task() -> None:
    """Test InMemoryTaskStore delete operation."""
    store = InMemoryTaskStore()

    task = await store.create_task(metadata=TaskMetadata(ttl=60000))

    deleted = await store.delete_task(task.taskId)
    assert deleted is True

    retrieved = await store.get_task(task.taskId)
    assert retrieved is None

    # Delete non-existent
    deleted = await store.delete_task(task.taskId)
    assert deleted is False

    store.cleanup()


@pytest.mark.anyio
async def test_get_all_tasks_helper() -> None:
    """Test the get_all_tasks debugging helper."""
    store = InMemoryTaskStore()

    await store.create_task(metadata=TaskMetadata(ttl=60000))
    await store.create_task(metadata=TaskMetadata(ttl=60000))

    all_tasks = store.get_all_tasks()
    assert len(all_tasks) == 2

    store.cleanup()


@pytest.mark.anyio
async def test_store_result_nonexistent_raises() -> None:
    """Test that storing result for nonexistent task raises ValueError."""
    store = InMemoryTaskStore()

    result = CallToolResult(content=[TextContent(type="text", text="Result")])

    with pytest.raises(ValueError, match="not found"):
        await store.store_result("nonexistent-id", result)

    store.cleanup()


@pytest.mark.anyio
async def test_create_task_with_null_ttl() -> None:
    """Test creating task with null TTL (never expires)."""
    store = InMemoryTaskStore()

    task = await store.create_task(metadata=TaskMetadata(ttl=None))

    assert task.ttl is None

    # Task should persist (not expire)
    retrieved = await store.get_task(task.taskId)
    assert retrieved is not None

    store.cleanup()


@pytest.mark.anyio
async def test_task_expiration_cleanup() -> None:
    """Test that expired tasks are cleaned up lazily."""
    store = InMemoryTaskStore()

    # Create a task with very short TTL
    task = await store.create_task(metadata=TaskMetadata(ttl=1))  # 1ms TTL

    # Manually force the expiry to be in the past
    stored = store._tasks.get(task.taskId)
    assert stored is not None
    stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)

    # Task should still exist in internal dict but be expired
    assert task.taskId in store._tasks

    # Any access operation should clean up expired tasks
    # list_tasks triggers cleanup
    tasks, _ = await store.list_tasks()

    # Expired task should be cleaned up
    assert task.taskId not in store._tasks
    assert len(tasks) == 0

    store.cleanup()


@pytest.mark.anyio
async def test_task_with_null_ttl_never_expires() -> None:
    """Test that tasks with null TTL never expire during cleanup."""

    store = InMemoryTaskStore()

    # Create task with null TTL
    task = await store.create_task(metadata=TaskMetadata(ttl=None))

    # Verify internal storage has no expiry
    stored = store._tasks.get(task.taskId)
    assert stored is not None
    assert stored.expires_at is None

    # Access operations should NOT remove this task
    await store.list_tasks()
    await store.get_task(task.taskId)

    # Task should still exist
    assert task.taskId in store._tasks
    retrieved = await store.get_task(task.taskId)
    assert retrieved is not None

    store.cleanup()


@pytest.mark.anyio
async def test_terminal_task_ttl_reset() -> None:
    """Test that TTL is reset when task enters terminal state."""

    store = InMemoryTaskStore()

    # Create task with short TTL
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))  # 60s

    # Get the initial expiry
    stored = store._tasks.get(task.taskId)
    assert stored is not None
    initial_expiry = stored.expires_at
    assert initial_expiry is not None

    # Update to terminal state (completed)
    await store.update_task(task.taskId, status="completed")

    # Expiry should be reset to a new time (from now + TTL)
    new_expiry = stored.expires_at
    assert new_expiry is not None
    assert new_expiry >= initial_expiry

    store.cleanup()


@pytest.mark.anyio
async def test_terminal_status_transition_rejected() -> None:
    """Test that transitions from terminal states are rejected.

    Per spec: Terminal states (completed, failed, cancelled) MUST NOT
    transition to any other status.
    """
    store = InMemoryTaskStore()

    # Test each terminal status
    for terminal_status in ("completed", "failed", "cancelled"):
        task = await store.create_task(metadata=TaskMetadata(ttl=60000))

        # Move to terminal state
        await store.update_task(task.taskId, status=terminal_status)

        # Attempting to transition to any other status should raise
        with pytest.raises(ValueError, match="Cannot transition from terminal status"):
            await store.update_task(task.taskId, status="working")

        # Also test transitioning to another terminal state
        other_terminal = "failed" if terminal_status != "failed" else "completed"
        with pytest.raises(ValueError, match="Cannot transition from terminal status"):
            await store.update_task(task.taskId, status=other_terminal)

    store.cleanup()


@pytest.mark.anyio
async def test_terminal_status_allows_same_status() -> None:
    """Test that setting the same terminal status doesn't raise.

    This is not a transition, so it should be allowed (no-op).
    """
    store = InMemoryTaskStore()

    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    await store.update_task(task.taskId, status="completed")

    # Setting the same status should not raise
    updated = await store.update_task(task.taskId, status="completed")
    assert updated.status == "completed"

    # Updating just the message should also work
    updated = await store.update_task(task.taskId, status_message="Updated message")
    assert updated.statusMessage == "Updated message"

    store.cleanup()


# =============================================================================
# cancel_task helper function tests
# =============================================================================


@pytest.mark.anyio
async def test_cancel_task_succeeds_for_working_task() -> None:
    """Test cancel_task helper succeeds for a working task."""
    store = InMemoryTaskStore()

    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    assert task.status == "working"

    result = await cancel_task(store, task.taskId)

    assert result.taskId == task.taskId
    assert result.status == "cancelled"

    # Verify store is updated
    retrieved = await store.get_task(task.taskId)
    assert retrieved is not None
    assert retrieved.status == "cancelled"

    store.cleanup()


@pytest.mark.anyio
async def test_cancel_task_rejects_nonexistent_task() -> None:
    """Test cancel_task raises McpError with INVALID_PARAMS for nonexistent task."""
    store = InMemoryTaskStore()

    with pytest.raises(McpError) as exc_info:
        await cancel_task(store, "nonexistent-task-id")

    assert exc_info.value.error.code == INVALID_PARAMS
    assert "not found" in exc_info.value.error.message

    store.cleanup()


@pytest.mark.anyio
async def test_cancel_task_rejects_completed_task() -> None:
    """Test cancel_task raises McpError with INVALID_PARAMS for completed task."""
    store = InMemoryTaskStore()

    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    await store.update_task(task.taskId, status="completed")

    with pytest.raises(McpError) as exc_info:
        await cancel_task(store, task.taskId)

    assert exc_info.value.error.code == INVALID_PARAMS
    assert "terminal state 'completed'" in exc_info.value.error.message

    store.cleanup()


@pytest.mark.anyio
async def test_cancel_task_rejects_failed_task() -> None:
    """Test cancel_task raises McpError with INVALID_PARAMS for failed task."""
    store = InMemoryTaskStore()

    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    await store.update_task(task.taskId, status="failed")

    with pytest.raises(McpError) as exc_info:
        await cancel_task(store, task.taskId)

    assert exc_info.value.error.code == INVALID_PARAMS
    assert "terminal state 'failed'" in exc_info.value.error.message

    store.cleanup()


@pytest.mark.anyio
async def test_cancel_task_rejects_already_cancelled_task() -> None:
    """Test cancel_task raises McpError with INVALID_PARAMS for already cancelled task."""
    store = InMemoryTaskStore()

    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    await store.update_task(task.taskId, status="cancelled")

    with pytest.raises(McpError) as exc_info:
        await cancel_task(store, task.taskId)

    assert exc_info.value.error.code == INVALID_PARAMS
    assert "terminal state 'cancelled'" in exc_info.value.error.message

    store.cleanup()


@pytest.mark.anyio
async def test_cancel_task_succeeds_for_input_required_task() -> None:
    """Test cancel_task helper succeeds for a task in input_required status."""
    store = InMemoryTaskStore()

    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    await store.update_task(task.taskId, status="input_required")

    result = await cancel_task(store, task.taskId)

    assert result.taskId == task.taskId
    assert result.status == "cancelled"

    store.cleanup()
