"""Tests for InMemoryTaskStore."""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest

from mcp.shared.exceptions import MCPError
from mcp.shared.experimental.tasks.helpers import cancel_task
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.types import INVALID_PARAMS, CallToolResult, TaskMetadata, TextContent


@pytest.fixture
async def store() -> AsyncIterator[InMemoryTaskStore]:
    """Provide a clean InMemoryTaskStore for each test with automatic cleanup."""
    store = InMemoryTaskStore()
    yield store
    store.cleanup()


@pytest.mark.anyio
async def test_create_and_get(store: InMemoryTaskStore) -> None:
    """Test InMemoryTaskStore create and get operations."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))

    assert task.task_id is not None
    assert task.status == "working"
    assert task.ttl == 60000

    retrieved = await store.get_task(task.task_id)
    assert retrieved is not None
    assert retrieved.task_id == task.task_id
    assert retrieved.status == "working"


@pytest.mark.anyio
async def test_create_with_custom_id(store: InMemoryTaskStore) -> None:
    """Test InMemoryTaskStore create with custom task ID."""
    task = await store.create_task(
        metadata=TaskMetadata(ttl=60000),
        task_id="my-custom-id",
    )

    assert task.task_id == "my-custom-id"
    assert task.status == "working"

    retrieved = await store.get_task("my-custom-id")
    assert retrieved is not None
    assert retrieved.task_id == "my-custom-id"


@pytest.mark.anyio
async def test_create_duplicate_id_raises(store: InMemoryTaskStore) -> None:
    """Test that creating a task with duplicate ID raises."""
    await store.create_task(metadata=TaskMetadata(ttl=60000), task_id="duplicate")

    with pytest.raises(ValueError, match="already exists"):
        await store.create_task(metadata=TaskMetadata(ttl=60000), task_id="duplicate")


@pytest.mark.anyio
async def test_get_nonexistent_returns_none(store: InMemoryTaskStore) -> None:
    """Test that getting a nonexistent task returns None."""
    retrieved = await store.get_task("nonexistent")
    assert retrieved is None


@pytest.mark.anyio
async def test_update_status(store: InMemoryTaskStore) -> None:
    """Test InMemoryTaskStore status updates."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))

    updated = await store.update_task(task.task_id, status="completed", status_message="All done!")

    assert updated.status == "completed"
    assert updated.status_message == "All done!"

    retrieved = await store.get_task(task.task_id)
    assert retrieved is not None
    assert retrieved.status == "completed"
    assert retrieved.status_message == "All done!"


@pytest.mark.anyio
async def test_update_nonexistent_raises(store: InMemoryTaskStore) -> None:
    """Test that updating a nonexistent task raises."""
    with pytest.raises(ValueError, match="not found"):
        await store.update_task("nonexistent", status="completed")


@pytest.mark.anyio
async def test_store_and_get_result(store: InMemoryTaskStore) -> None:
    """Test InMemoryTaskStore result storage and retrieval."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))

    # Store result
    result = CallToolResult(content=[TextContent(type="text", text="Result data")])
    await store.store_result(task.task_id, result)

    # Retrieve result
    retrieved_result = await store.get_result(task.task_id)
    assert retrieved_result == result


@pytest.mark.anyio
async def test_get_result_nonexistent_returns_none(store: InMemoryTaskStore) -> None:
    """Test that getting result for nonexistent task returns None."""
    result = await store.get_result("nonexistent")
    assert result is None


@pytest.mark.anyio
async def test_get_result_no_result_returns_none(store: InMemoryTaskStore) -> None:
    """Test that getting result when none stored returns None."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    result = await store.get_result(task.task_id)
    assert result is None


@pytest.mark.anyio
async def test_list_tasks(store: InMemoryTaskStore) -> None:
    """Test InMemoryTaskStore list operation."""
    # Create multiple tasks
    for _ in range(3):
        await store.create_task(metadata=TaskMetadata(ttl=60000))

    tasks, next_cursor = await store.list_tasks()
    assert len(tasks) == 3
    assert next_cursor is None  # Less than page size


@pytest.mark.anyio
async def test_list_tasks_pagination() -> None:
    """Test InMemoryTaskStore pagination."""
    # Needs custom page_size, can't use fixture
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
async def test_list_tasks_invalid_cursor(store: InMemoryTaskStore) -> None:
    """Test that invalid cursor raises."""
    await store.create_task(metadata=TaskMetadata(ttl=60000))

    with pytest.raises(ValueError, match="Invalid cursor"):
        await store.list_tasks(cursor="invalid-cursor")


@pytest.mark.anyio
async def test_delete_task(store: InMemoryTaskStore) -> None:
    """Test InMemoryTaskStore delete operation."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))

    deleted = await store.delete_task(task.task_id)
    assert deleted is True

    retrieved = await store.get_task(task.task_id)
    assert retrieved is None

    # Delete non-existent
    deleted = await store.delete_task(task.task_id)
    assert deleted is False


@pytest.mark.anyio
async def test_get_all_tasks_helper(store: InMemoryTaskStore) -> None:
    """Test the get_all_tasks debugging helper."""
    await store.create_task(metadata=TaskMetadata(ttl=60000))
    await store.create_task(metadata=TaskMetadata(ttl=60000))

    all_tasks = store.get_all_tasks()
    assert len(all_tasks) == 2


@pytest.mark.anyio
async def test_store_result_nonexistent_raises(store: InMemoryTaskStore) -> None:
    """Test that storing result for nonexistent task raises ValueError."""
    result = CallToolResult(content=[TextContent(type="text", text="Result")])

    with pytest.raises(ValueError, match="not found"):
        await store.store_result("nonexistent-id", result)


@pytest.mark.anyio
async def test_create_task_with_null_ttl(store: InMemoryTaskStore) -> None:
    """Test creating task with null TTL (never expires)."""
    task = await store.create_task(metadata=TaskMetadata(ttl=None))

    assert task.ttl is None

    # Task should persist (not expire)
    retrieved = await store.get_task(task.task_id)
    assert retrieved is not None


@pytest.mark.anyio
async def test_task_expiration_cleanup(store: InMemoryTaskStore) -> None:
    """Test that expired tasks are cleaned up lazily."""
    # Create a task with very short TTL
    task = await store.create_task(metadata=TaskMetadata(ttl=1))  # 1ms TTL

    # Manually force the expiry to be in the past
    stored = store._tasks.get(task.task_id)
    assert stored is not None
    stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)

    # Task should still exist in internal dict but be expired
    assert task.task_id in store._tasks

    # Any access operation should clean up expired tasks
    # list_tasks triggers cleanup
    tasks, _ = await store.list_tasks()

    # Expired task should be cleaned up
    assert task.task_id not in store._tasks
    assert len(tasks) == 0


@pytest.mark.anyio
async def test_task_with_null_ttl_never_expires(store: InMemoryTaskStore) -> None:
    """Test that tasks with null TTL never expire during cleanup."""
    # Create task with null TTL
    task = await store.create_task(metadata=TaskMetadata(ttl=None))

    # Verify internal storage has no expiry
    stored = store._tasks.get(task.task_id)
    assert stored is not None
    assert stored.expires_at is None

    # Access operations should NOT remove this task
    await store.list_tasks()
    await store.get_task(task.task_id)

    # Task should still exist
    assert task.task_id in store._tasks
    retrieved = await store.get_task(task.task_id)
    assert retrieved is not None


@pytest.mark.anyio
async def test_terminal_task_ttl_reset(store: InMemoryTaskStore) -> None:
    """Test that TTL is reset when task enters terminal state."""
    # Create task with short TTL
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))  # 60s

    # Get the initial expiry
    stored = store._tasks.get(task.task_id)
    assert stored is not None
    initial_expiry = stored.expires_at
    assert initial_expiry is not None

    # Update to terminal state (completed)
    await store.update_task(task.task_id, status="completed")

    # Expiry should be reset to a new time (from now + TTL)
    new_expiry = stored.expires_at
    assert new_expiry is not None
    assert new_expiry >= initial_expiry


@pytest.mark.anyio
async def test_terminal_status_transition_rejected(store: InMemoryTaskStore) -> None:
    """Test that transitions from terminal states are rejected.

    Per spec: Terminal states (completed, failed, cancelled) MUST NOT
    transition to any other status.
    """
    # Test each terminal status
    for terminal_status in ("completed", "failed", "cancelled"):
        task = await store.create_task(metadata=TaskMetadata(ttl=60000))

        # Move to terminal state
        await store.update_task(task.task_id, status=terminal_status)

        # Attempting to transition to any other status should raise
        with pytest.raises(ValueError, match="Cannot transition from terminal status"):
            await store.update_task(task.task_id, status="working")

        # Also test transitioning to another terminal state
        other_terminal = "failed" if terminal_status != "failed" else "completed"
        with pytest.raises(ValueError, match="Cannot transition from terminal status"):
            await store.update_task(task.task_id, status=other_terminal)


@pytest.mark.anyio
async def test_terminal_status_allows_same_status(store: InMemoryTaskStore) -> None:
    """Test that setting the same terminal status doesn't raise.

    This is not a transition, so it should be allowed (no-op).
    """
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    await store.update_task(task.task_id, status="completed")

    # Setting the same status should not raise
    updated = await store.update_task(task.task_id, status="completed")
    assert updated.status == "completed"

    # Updating just the message should also work
    updated = await store.update_task(task.task_id, status_message="Updated message")
    assert updated.status_message == "Updated message"


@pytest.mark.anyio
async def test_wait_for_update_nonexistent_raises(store: InMemoryTaskStore) -> None:
    """Test that wait_for_update raises for nonexistent task."""
    with pytest.raises(ValueError, match="not found"):
        await store.wait_for_update("nonexistent-task-id")


@pytest.mark.anyio
async def test_cancel_task_succeeds_for_working_task(store: InMemoryTaskStore) -> None:
    """Test cancel_task helper succeeds for a working task."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    assert task.status == "working"

    result = await cancel_task(store, task.task_id)

    assert result.task_id == task.task_id
    assert result.status == "cancelled"

    # Verify store is updated
    retrieved = await store.get_task(task.task_id)
    assert retrieved is not None
    assert retrieved.status == "cancelled"


@pytest.mark.anyio
async def test_cancel_task_rejects_nonexistent_task(store: InMemoryTaskStore) -> None:
    """Test cancel_task raises MCPError with INVALID_PARAMS for nonexistent task."""
    with pytest.raises(MCPError) as exc_info:
        await cancel_task(store, "nonexistent-task-id")

    assert exc_info.value.error.code == INVALID_PARAMS
    assert "not found" in exc_info.value.error.message


@pytest.mark.anyio
async def test_cancel_task_rejects_completed_task(store: InMemoryTaskStore) -> None:
    """Test cancel_task raises MCPError with INVALID_PARAMS for completed task."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    await store.update_task(task.task_id, status="completed")

    with pytest.raises(MCPError) as exc_info:
        await cancel_task(store, task.task_id)

    assert exc_info.value.error.code == INVALID_PARAMS
    assert "terminal state 'completed'" in exc_info.value.error.message


@pytest.mark.anyio
async def test_cancel_task_rejects_failed_task(store: InMemoryTaskStore) -> None:
    """Test cancel_task raises MCPError with INVALID_PARAMS for failed task."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    await store.update_task(task.task_id, status="failed")

    with pytest.raises(MCPError) as exc_info:
        await cancel_task(store, task.task_id)

    assert exc_info.value.error.code == INVALID_PARAMS
    assert "terminal state 'failed'" in exc_info.value.error.message


@pytest.mark.anyio
async def test_cancel_task_rejects_already_cancelled_task(store: InMemoryTaskStore) -> None:
    """Test cancel_task raises MCPError with INVALID_PARAMS for already cancelled task."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    await store.update_task(task.task_id, status="cancelled")

    with pytest.raises(MCPError) as exc_info:
        await cancel_task(store, task.task_id)

    assert exc_info.value.error.code == INVALID_PARAMS
    assert "terminal state 'cancelled'" in exc_info.value.error.message


@pytest.mark.anyio
async def test_cancel_task_succeeds_for_input_required_task(store: InMemoryTaskStore) -> None:
    """Test cancel_task helper succeeds for a task in input_required status."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))
    await store.update_task(task.task_id, status="input_required")

    result = await cancel_task(store, task.task_id)

    assert result.task_id == task.task_id
    assert result.status == "cancelled"


# --- Session isolation tests ---


@pytest.mark.anyio
async def test_session_b_cannot_list_tasks_created_by_session_a(store: InMemoryTaskStore) -> None:
    """Test that session-b cannot list tasks created by session-a."""
    await store.create_task(metadata=TaskMetadata(ttl=60000), session_id="session-a")
    await store.create_task(metadata=TaskMetadata(ttl=60000), session_id="session-a")

    tasks, _ = await store.list_tasks(session_id="session-b")
    assert len(tasks) == 0


@pytest.mark.anyio
async def test_session_b_cannot_read_task_created_by_session_a(store: InMemoryTaskStore) -> None:
    """Test that session-b cannot read a task created by session-a."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000), session_id="session-a")

    result = await store.get_task(task.task_id, session_id="session-b")
    assert result is None


@pytest.mark.anyio
async def test_session_b_cannot_update_task_created_by_session_a(store: InMemoryTaskStore) -> None:
    """Test that session-b cannot update a task created by session-a."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000), session_id="session-a")

    with pytest.raises(ValueError, match="not found"):
        await store.update_task(task.task_id, status="cancelled", session_id="session-b")


@pytest.mark.anyio
async def test_session_b_cannot_store_result_on_session_a_task(store: InMemoryTaskStore) -> None:
    """Test that session-b cannot store a result on session-a's task."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000), session_id="session-a")
    result = CallToolResult(content=[TextContent(type="text", text="secret")])

    with pytest.raises(ValueError, match="not found"):
        await store.store_result(task.task_id, result, session_id="session-b")


@pytest.mark.anyio
async def test_session_b_cannot_get_result_of_session_a_task(store: InMemoryTaskStore) -> None:
    """Test that session-b cannot get the result of session-a's task."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000), session_id="session-a")
    result = CallToolResult(content=[TextContent(type="text", text="secret")])
    await store.store_result(task.task_id, result, session_id="session-a")

    retrieved = await store.get_result(task.task_id, session_id="session-b")
    assert retrieved is None


@pytest.mark.anyio
async def test_session_b_cannot_delete_task_created_by_session_a(store: InMemoryTaskStore) -> None:
    """Test that session-b cannot delete a task created by session-a."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000), session_id="session-a")

    deleted = await store.delete_task(task.task_id, session_id="session-b")
    assert deleted is False

    # Task should still exist for session-a
    retrieved = await store.get_task(task.task_id, session_id="session-a")
    assert retrieved is not None


@pytest.mark.anyio
async def test_owning_session_can_access_its_own_tasks(store: InMemoryTaskStore) -> None:
    """Test that the owning session can access its own tasks."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000), session_id="session-a")

    retrieved = await store.get_task(task.task_id, session_id="session-a")
    assert retrieved is not None
    assert retrieved.task_id == task.task_id


@pytest.mark.anyio
async def test_list_only_tasks_belonging_to_requesting_session(store: InMemoryTaskStore) -> None:
    """Test that list_tasks returns only tasks belonging to the requesting session."""
    await store.create_task(metadata=TaskMetadata(ttl=60000), session_id="session-a")
    await store.create_task(metadata=TaskMetadata(ttl=60000), session_id="session-b")
    await store.create_task(metadata=TaskMetadata(ttl=60000), session_id="session-a")

    tasks_a, _ = await store.list_tasks(session_id="session-a")
    assert len(tasks_a) == 2

    tasks_b, _ = await store.list_tasks(session_id="session-b")
    assert len(tasks_b) == 1


@pytest.mark.anyio
async def test_no_session_id_allows_access_backward_compat(store: InMemoryTaskStore) -> None:
    """Test backward compatibility: no session_id on read allows access to all tasks."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000), session_id="session-a")

    # No session_id on read = no filtering
    retrieved = await store.get_task(task.task_id)
    assert retrieved is not None


@pytest.mark.anyio
async def test_task_created_without_session_id_accessible_by_any_session(store: InMemoryTaskStore) -> None:
    """Test that tasks created without session_id are accessible by any session."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000))

    # Any session_id on read should still see the task
    retrieved = await store.get_task(task.task_id, session_id="session-b")
    assert retrieved is not None


@pytest.mark.anyio
async def test_session_isolation_pagination() -> None:
    """Test that pagination works correctly within a session."""
    store = InMemoryTaskStore(page_size=10)

    # Create 15 tasks for session-a, 5 for session-b
    for _ in range(15):
        await store.create_task(metadata=TaskMetadata(ttl=60000), session_id="session-a")
    for _ in range(5):
        await store.create_task(metadata=TaskMetadata(ttl=60000), session_id="session-b")

    # First page for session-a should have 10
    page1, next_cursor = await store.list_tasks(session_id="session-a")
    assert len(page1) == 10
    assert next_cursor is not None

    # Second page for session-a should have 5
    page2, next_cursor = await store.list_tasks(cursor=next_cursor, session_id="session-a")
    assert len(page2) == 5
    assert next_cursor is None

    # session-b should only see its 5
    tasks_b, next_cursor = await store.list_tasks(session_id="session-b")
    assert len(tasks_b) == 5
    assert next_cursor is None

    store.cleanup()


@pytest.mark.anyio
async def test_cancel_task_with_session_isolation(store: InMemoryTaskStore) -> None:
    """Test that cancel_task respects session isolation."""
    task = await store.create_task(metadata=TaskMetadata(ttl=60000), session_id="session-a")

    # session-b should not be able to cancel session-a's task
    with pytest.raises(MCPError) as exc_info:
        await cancel_task(store, task.task_id, session_id="session-b")
    assert exc_info.value.error.code == INVALID_PARAMS
    assert "not found" in exc_info.value.error.message

    # session-a should be able to cancel its own task
    result = await cancel_task(store, task.task_id, session_id="session-a")
    assert result.status == "cancelled"
