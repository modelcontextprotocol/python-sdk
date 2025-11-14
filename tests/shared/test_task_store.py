"""Unit tests for TaskStore implementation."""

import asyncio

import pytest

from examples.shared.in_memory_task_store import InMemoryTaskStore
from mcp.types import CallToolRequest, CallToolRequestParams, RequestId, TaskMetadata


@pytest.fixture
def task_store() -> InMemoryTaskStore:
    """Create a fresh InMemoryTaskStore for each test."""
    return InMemoryTaskStore()


@pytest.fixture
def sample_task_metadata() -> TaskMetadata:
    """Create sample task metadata."""
    return TaskMetadata(taskId="test-task-123", keepAlive=5000)


@pytest.fixture
def sample_request() -> CallToolRequest:
    """Create a sample request."""
    return CallToolRequest(params=CallToolRequestParams(name="test_tool", arguments={"arg": "value"}))


class TestCreateTask:
    """Tests for TaskStore.create_task()."""

    @pytest.mark.anyio
    async def test_create_task_basic(
        self, task_store: InMemoryTaskStore, sample_task_metadata: TaskMetadata, sample_request: CallToolRequest
    ):
        """Test creating a basic task."""
        request_id: RequestId = "req-1"
        await task_store.create_task(sample_task_metadata, request_id, sample_request)

        # Verify task was created with correct initial state
        task = await task_store.get_task("test-task-123")
        assert task is not None
        assert task.taskId == "test-task-123"
        assert task.status == "submitted"
        assert task.keepAlive == 5000
        assert task.pollInterval == 500  # Default value

    @pytest.mark.anyio
    async def test_create_task_without_keep_alive(self, task_store: InMemoryTaskStore, sample_request: CallToolRequest):
        """Test creating a task without keepAlive."""
        task_metadata = TaskMetadata(taskId="test-task-no-keepalive")
        request_id: RequestId = "req-2"
        await task_store.create_task(task_metadata, request_id, sample_request)

        task = await task_store.get_task("test-task-no-keepalive")
        assert task is not None
        assert task.keepAlive is None
        # Should not schedule cleanup if no keepAlive
        assert "test-task-no-keepalive" not in task_store._cleanup_tasks

    @pytest.mark.anyio
    async def test_create_task_schedules_cleanup(
        self, task_store: InMemoryTaskStore, sample_task_metadata: TaskMetadata, sample_request: CallToolRequest
    ):
        """Test that creating a task with keepAlive schedules cleanup."""
        request_id: RequestId = "req-3"
        await task_store.create_task(sample_task_metadata, request_id, sample_request)

        # Verify cleanup task was scheduled
        assert "test-task-123" in task_store._cleanup_tasks
        cleanup_task = task_store._cleanup_tasks["test-task-123"]
        assert not cleanup_task.done()

    @pytest.mark.anyio
    async def test_create_duplicate_task_raises_error(
        self, task_store: InMemoryTaskStore, sample_task_metadata: TaskMetadata, sample_request: CallToolRequest
    ):
        """Test that creating a task with duplicate ID raises ValueError."""
        request_id: RequestId = "req-4"
        await task_store.create_task(sample_task_metadata, request_id, sample_request)

        # Attempt to create another task with same ID
        with pytest.raises(ValueError, match="Task with ID test-task-123 already exists"):
            await task_store.create_task(sample_task_metadata, "req-5", sample_request)


class TestGetTask:
    """Tests for TaskStore.get_task()."""

    @pytest.mark.anyio
    async def test_get_existing_task(
        self, task_store: InMemoryTaskStore, sample_task_metadata: TaskMetadata, sample_request: CallToolRequest
    ):
        """Test retrieving an existing task."""
        request_id: RequestId = "req-6"
        await task_store.create_task(sample_task_metadata, request_id, sample_request)

        task = await task_store.get_task("test-task-123")
        assert task is not None
        assert task.taskId == "test-task-123"
        assert task.status == "submitted"

    @pytest.mark.anyio
    async def test_get_nonexistent_task_returns_none(self, task_store: InMemoryTaskStore):
        """Test that getting a non-existent task returns None."""
        task = await task_store.get_task("nonexistent-task")
        assert task is None


class TestStoreTaskResult:
    """Tests for TaskStore.store_task_result()."""

    @pytest.mark.anyio
    async def test_store_result_for_completed_task(
        self, task_store: InMemoryTaskStore, sample_task_metadata: TaskMetadata, sample_request: CallToolRequest
    ):
        """Test storing a result for a completed task."""
        from mcp.types import CallToolResult, TextContent

        request_id: RequestId = "req-7"
        await task_store.create_task(sample_task_metadata, request_id, sample_request)

        # Update task to completed status
        await task_store.update_task_status("test-task-123", "completed")

        # Store result
        result = CallToolResult(content=[TextContent(type="text", text="Success!")])
        await task_store.store_task_result("test-task-123", result)

        # Verify result was stored
        retrieved_result = await task_store.get_task_result("test-task-123")
        retrieved_result = CallToolResult.model_validate(retrieved_result)
        assert isinstance(retrieved_result.content[0], TextContent)
        assert retrieved_result.content[0].text == "Success!"


class TestGetTaskResult:
    """Tests for TaskStore.get_task_result()."""

    @pytest.mark.anyio
    async def test_get_result_for_completed_task(
        self, task_store: InMemoryTaskStore, sample_task_metadata: TaskMetadata, sample_request: CallToolRequest
    ):
        """Test retrieving result for a completed task."""
        from mcp.types import CallToolResult, TextContent

        request_id: RequestId = "req-8"
        await task_store.create_task(sample_task_metadata, request_id, sample_request)
        await task_store.update_task_status("test-task-123", "completed")

        result = CallToolResult(content=[TextContent(type="text", text="Result!")])
        await task_store.store_task_result("test-task-123", result)

        retrieved_result = await task_store.get_task_result("test-task-123")
        retrieved_result = CallToolResult.model_validate(retrieved_result)
        assert isinstance(retrieved_result.content[0], TextContent)
        assert retrieved_result.content[0].text == "Result!"

    @pytest.mark.anyio
    async def test_get_result_for_incomplete_task_raises_error(
        self, task_store: InMemoryTaskStore, sample_task_metadata: TaskMetadata, sample_request: CallToolRequest
    ):
        """Test that getting result for incomplete task raises ValueError."""
        request_id: RequestId = "req-9"
        await task_store.create_task(sample_task_metadata, request_id, sample_request)

        # Task is still in 'submitted' status
        with pytest.raises(ValueError, match="Task test-task-123 has no result stored"):
            await task_store.get_task_result("test-task-123")

    @pytest.mark.anyio
    async def test_get_result_for_nonexistent_task_raises_error(self, task_store: InMemoryTaskStore):
        """Test that getting result for non-existent task raises ValueError."""
        with pytest.raises(ValueError, match="Task with ID nonexistent not found"):
            await task_store.get_task_result("nonexistent")


class TestUpdateTaskStatus:
    """Tests for TaskStore.update_task_status()."""

    @pytest.mark.anyio
    async def test_update_status_to_working(
        self, task_store: InMemoryTaskStore, sample_task_metadata: TaskMetadata, sample_request: CallToolRequest
    ):
        """Test updating task status to working."""
        request_id: RequestId = "req-10"
        await task_store.create_task(sample_task_metadata, request_id, sample_request)

        await task_store.update_task_status("test-task-123", "working")

        task = await task_store.get_task("test-task-123")
        assert task
        assert task.status == "working"

    @pytest.mark.anyio
    async def test_update_status_to_completed(
        self, task_store: InMemoryTaskStore, sample_task_metadata: TaskMetadata, sample_request: CallToolRequest
    ):
        """Test updating task status to completed."""
        request_id: RequestId = "req-11"
        await task_store.create_task(sample_task_metadata, request_id, sample_request)

        await task_store.update_task_status("test-task-123", "completed")

        task = await task_store.get_task("test-task-123")
        assert task
        assert task.status == "completed"
        assert task.error is None

    @pytest.mark.anyio
    async def test_update_status_to_failed_with_error(
        self, task_store: InMemoryTaskStore, sample_task_metadata: TaskMetadata, sample_request: CallToolRequest
    ):
        """Test updating task status to failed with error message."""
        request_id: RequestId = "req-12"
        await task_store.create_task(sample_task_metadata, request_id, sample_request)

        await task_store.update_task_status("test-task-123", "failed", error="Something went wrong")

        task = await task_store.get_task("test-task-123")
        assert task
        assert task.status == "failed"
        assert task.error == "Something went wrong"

    @pytest.mark.anyio
    async def test_update_status_to_terminal_reschedules_cleanup(
        self, task_store: InMemoryTaskStore, sample_task_metadata: TaskMetadata, sample_request: CallToolRequest
    ):
        """Test that updating status to terminal state reschedules cleanup."""
        request_id: RequestId = "req-13"
        await task_store.create_task(sample_task_metadata, request_id, sample_request)

        # Verify cleanup was scheduled
        assert "test-task-123" in task_store._cleanup_tasks
        original_cleanup = task_store._cleanup_tasks["test-task-123"]

        # Update status to 'completed' (terminal state, should cancel old and reschedule new cleanup)
        await task_store.update_task_status("test-task-123", "completed")

        # Give the cancellation a moment to complete
        await asyncio.sleep(0)

        # Original cleanup should be cancelled
        assert original_cleanup.cancelled()
        # New cleanup should be scheduled
        assert "test-task-123" in task_store._cleanup_tasks
        new_cleanup = task_store._cleanup_tasks["test-task-123"]
        assert new_cleanup != original_cleanup
        assert not new_cleanup.done()

    @pytest.mark.anyio
    async def test_update_nonexistent_task_raises_error(self, task_store: InMemoryTaskStore):
        """Test that updating non-existent task raises ValueError."""
        with pytest.raises(ValueError, match="Task with ID nonexistent not found"):
            await task_store.update_task_status("nonexistent", "completed")


class TestListTasks:
    """Tests for TaskStore.list_tasks()."""

    @pytest.mark.anyio
    async def test_list_tasks_empty(self, task_store: InMemoryTaskStore):
        """Test listing tasks when store is empty."""
        result = await task_store.list_tasks()
        assert result["tasks"] == []
        assert result.get("nextCursor") is None

    @pytest.mark.anyio
    async def test_list_tasks_single_page(self, task_store: InMemoryTaskStore, sample_request: CallToolRequest):
        """Test listing tasks that fit on a single page."""
        # Create 3 tasks
        for i in range(3):
            task_meta = TaskMetadata(taskId=f"task-{i}")
            await task_store.create_task(task_meta, f"req-{i}", sample_request)

        result = await task_store.list_tasks()
        assert len(result["tasks"]) == 3
        assert result.get("nextCursor") is None

    @pytest.mark.anyio
    async def test_list_tasks_pagination(self, task_store: InMemoryTaskStore, sample_request: CallToolRequest):
        """Test listing tasks with pagination."""
        # Create 15 tasks (more than PAGE_SIZE=10)
        for i in range(15):
            task_meta = TaskMetadata(taskId=f"task-{i:02d}")
            await task_store.create_task(task_meta, f"req-{i}", sample_request)

        # First page
        result = await task_store.list_tasks()
        assert len(result["tasks"]) == 10
        assert result["nextCursor"] is not None

        # Second page
        result2 = await task_store.list_tasks(cursor=result["nextCursor"])
        assert len(result2["tasks"]) == 5
        assert result2.get("nextCursor") is None

    @pytest.mark.anyio
    async def test_list_tasks_invalid_cursor_raises_error(self, task_store: InMemoryTaskStore):
        """Test that invalid cursor raises ValueError."""
        with pytest.raises(ValueError, match="Invalid cursor"):
            await task_store.list_tasks(cursor="invalid-cursor")


class TestTaskCleanup:
    """Tests for task cleanup functionality."""

    @pytest.mark.anyio
    async def test_cleanup_removes_completed_task(self, task_store: InMemoryTaskStore, sample_request: CallToolRequest):
        """Test that cleanup removes task after keepAlive expires."""
        # Create task with very short keepAlive
        task_meta = TaskMetadata(taskId="cleanup-task", keepAlive=100)  # 100ms
        await task_store.create_task(task_meta, "req-cleanup", sample_request)

        # Update to completed to trigger cleanup timer
        await task_store.update_task_status("cleanup-task", "completed")

        # Wait for cleanup (100ms + small buffer)
        await asyncio.sleep(0.15)

        # Task should be removed
        task = await task_store.get_task("cleanup-task")
        assert task is None

    @pytest.mark.anyio
    async def test_cleanup_rescheduled_on_terminal_status(
        self, task_store: InMemoryTaskStore, sample_request: CallToolRequest
    ):
        """Test that cleanup is rescheduled when updating to terminal status."""
        task_meta = TaskMetadata(taskId="cancel-cleanup-task", keepAlive=5000)
        await task_store.create_task(task_meta, "req-cancel", sample_request)

        # Update to completed (starts cleanup timer)
        await task_store.update_task_status("cancel-cleanup-task", "completed")

        cleanup_task = task_store._cleanup_tasks.get("cancel-cleanup-task")
        assert cleanup_task is not None
        assert not cleanup_task.done()

        # Keep a reference to the first cleanup task
        first_cleanup = cleanup_task

        # Update status again to 'failed' (terminal state, should reschedule cleanup)
        await task_store.update_task_status("cancel-cleanup-task", "failed")

        # Give the cancellation a moment to complete
        await asyncio.sleep(0)

        # First cleanup should be cancelled
        assert first_cleanup.cancelled()
        # New cleanup should be scheduled
        assert "cancel-cleanup-task" in task_store._cleanup_tasks
        second_cleanup = task_store._cleanup_tasks["cancel-cleanup-task"]
        assert second_cleanup != first_cleanup
        assert not second_cleanup.done()
