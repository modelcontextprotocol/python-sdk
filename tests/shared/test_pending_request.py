"""Unit tests for PendingRequest implementation."""

import asyncio
from collections.abc import Awaitable
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp.shared.request import DEFAULT_POLLING_INTERVAL, PendingRequest, TaskHandlerOptions
from mcp.types import CallToolResult, GetTaskResult, TextContent


@pytest.fixture
def mock_session() -> MagicMock:
    """Create a mock session for testing."""
    session = MagicMock()
    session.get_task = AsyncMock()
    session.get_task_result = AsyncMock()
    return session


@pytest.fixture
def sample_result() -> CallToolResult:
    """Create a sample result."""
    return CallToolResult(content=[TextContent(type="text", text="Success!")])


class TestPendingRequestWithoutTask:
    """Tests for PendingRequest without task ID (direct execution)."""

    @pytest.mark.anyio
    async def test_result_without_task_id(self, mock_session: MagicMock, sample_result: CallToolResult):
        """Test that request without task ID returns result directly."""

        async def get_result():
            return sample_result

        # Create a never-completing coroutine for task_created_handle
        # It won't be awaited since task_id is None
        never_completes_future: Awaitable[None] = asyncio.Future()

        pending = PendingRequest(
            session=mock_session,
            task_created_handle=never_completes_future,
            result_handle=get_result(),
            result_type=CallToolResult,
            task_id=None,
        )

        result = await pending.result()
        assert result == sample_result
        # Task methods should never be called
        mock_session.get_task.assert_not_called()
        mock_session.get_task_result.assert_not_called()

    @pytest.mark.anyio
    async def test_callbacks_not_invoked_without_task_id(self, mock_session: MagicMock, sample_result: CallToolResult):
        """Test that callbacks are not invoked when no task ID is provided."""

        async def get_result():
            return sample_result

        # Create a never-completing future for task_created_handle
        # It won't be awaited since task_id is None
        never_completes_future: Awaitable[None] = asyncio.Future()

        on_task_created = AsyncMock()
        on_task_status = AsyncMock()

        pending = PendingRequest(
            session=mock_session,
            task_created_handle=never_completes_future,
            result_handle=get_result(),
            result_type=CallToolResult,
            task_id=None,
        )

        await pending.result(TaskHandlerOptions(on_task_created=on_task_created, on_task_status=on_task_status))

        # Callbacks should not be invoked
        on_task_created.assert_not_called()
        on_task_status.assert_not_called()


class TestPendingRequestTaskPolling:
    """Tests for PendingRequest with task-based execution."""

    @pytest.mark.anyio
    async def test_task_polling_basic_flow(self, mock_session: MagicMock, sample_result: CallToolResult):
        """Test basic task polling flow: submitted -> working -> completed."""
        task_created_event = asyncio.Event()

        async def task_created():
            await task_created_event.wait()

        async def never_completes():
            await asyncio.Future()  # Never completes
            return sample_result

        # Set up task status progression
        mock_session.get_task.side_effect = [
            GetTaskResult(taskId="task-1", status="submitted", pollInterval=100),
            GetTaskResult(taskId="task-1", status="working", pollInterval=100),
            GetTaskResult(taskId="task-1", status="completed", pollInterval=100),
        ]
        mock_session.get_task_result.return_value = sample_result

        pending = PendingRequest(
            session=mock_session,
            task_created_handle=task_created(),
            result_handle=never_completes(),
            result_type=CallToolResult,
            task_id="task-1",
        )

        # Trigger task created notification after a short delay
        async def notify_created():
            await asyncio.sleep(0.01)
            task_created_event.set()

        asyncio.create_task(notify_created())

        result = await pending.result()
        assert result == sample_result
        assert mock_session.get_task.call_count == 3
        mock_session.get_task_result.assert_called_once_with("task-1", CallToolResult)

    @pytest.mark.anyio
    async def test_callback_invocation_timing(self, mock_session: MagicMock, sample_result: CallToolResult):
        """Test that callbacks are invoked at the correct times."""
        task_created_event = asyncio.Event()

        async def task_created():
            await task_created_event.wait()

        async def never_completes():
            await asyncio.Future()  # Never completes
            return sample_result

        on_task_created = AsyncMock()
        on_task_status = AsyncMock()

        # Set up task status progression
        task_statuses = [
            GetTaskResult(taskId="task-2", status="submitted", pollInterval=50),
            GetTaskResult(taskId="task-2", status="completed", pollInterval=50),
        ]
        mock_session.get_task.side_effect = task_statuses
        mock_session.get_task_result.return_value = sample_result

        pending = PendingRequest(
            session=mock_session,
            task_created_handle=task_created(),
            result_handle=never_completes(),
            result_type=CallToolResult,
            task_id="task-2",
        )

        # Trigger task created notification
        async def notify_created():
            await asyncio.sleep(0.01)
            task_created_event.set()

        asyncio.create_task(notify_created())

        await pending.result(TaskHandlerOptions(on_task_created=on_task_created, on_task_status=on_task_status))

        # Verify callback invocations
        on_task_created.assert_called_once()
        assert on_task_status.call_count == 2
        # Check that status callback was called with each status
        assert on_task_status.call_args_list[0][0][0].status == "submitted"
        assert on_task_status.call_args_list[1][0][0].status == "completed"

    @pytest.mark.anyio
    async def test_polling_interval_respects_poll_frequency(
        self, mock_session: MagicMock, sample_result: CallToolResult
    ):
        """Test that polling interval respects pollInterval from task."""
        task_created_event = asyncio.Event()
        task_created_event.set()

        async def task_created():
            pass

        async def never_completes():
            await asyncio.Future()  # Never completes
            return sample_result

        # Track polling timestamps
        poll_times: list[float] = []

        async def mock_get_task(task_id: str):
            poll_times.append(asyncio.get_event_loop().time())
            if len(poll_times) == 1:
                return GetTaskResult(taskId=task_id, status="submitted", pollInterval=100)  # 100ms
            else:
                return GetTaskResult(taskId=task_id, status="completed", pollInterval=100)

        mock_session.get_task.side_effect = mock_get_task
        mock_session.get_task_result.return_value = sample_result

        pending = PendingRequest(
            session=mock_session,
            task_created_handle=task_created(),
            result_handle=never_completes(),
            result_type=CallToolResult,
            task_id="task-3",
        )

        await pending.result()

        # Verify polling interval (should be ~100ms between polls)
        assert len(poll_times) == 2
        interval = poll_times[1] - poll_times[0]
        # Allow some tolerance for timing variance
        assert 0.08 < interval < 0.15

    @pytest.mark.anyio
    async def test_polling_uses_default_interval_when_not_specified(
        self, mock_session: MagicMock, sample_result: CallToolResult
    ):
        """Test that default polling interval is used when pollInterval is None."""
        task_created_event = asyncio.Event()
        task_created_event.set()

        async def task_created():
            pass

        async def never_completes():
            await asyncio.Future()  # Never completes
            return sample_result

        poll_times: list[float] = []

        async def mock_get_task(task_id: str):
            poll_times.append(asyncio.get_event_loop().time())
            if len(poll_times) == 1:
                return GetTaskResult(taskId=task_id, status="submitted", pollInterval=None)
            else:
                return GetTaskResult(taskId=task_id, status="completed", pollInterval=None)

        mock_session.get_task.side_effect = mock_get_task
        mock_session.get_task_result.return_value = sample_result

        pending = PendingRequest(
            session=mock_session,
            task_created_handle=task_created(),
            result_handle=never_completes(),
            result_type=CallToolResult,
            task_id="task-4",
        )

        await pending.result()

        # Verify default polling interval (DEFAULT_POLLING_INTERVAL = 5 seconds)
        assert len(poll_times) == 2
        interval = poll_times[1] - poll_times[0]
        # Default is 5 seconds, allow some tolerance
        assert DEFAULT_POLLING_INTERVAL - 0.5 < interval < DEFAULT_POLLING_INTERVAL + 0.5


class TestPendingRequestRaceCondition:
    """Tests for race condition handling between task polling and direct result."""

    @pytest.mark.anyio
    async def test_direct_result_wins_race(self, mock_session: MagicMock, sample_result: CallToolResult):
        """Test that direct result path can complete before task polling."""
        result_event = asyncio.Event()
        task_created_event = asyncio.Event()

        async def task_created():
            await task_created_event.wait()

        async def get_result():
            await result_event.wait()
            return sample_result

        # Set up task polling to be slow
        async def slow_get_task(task_id: str):
            await asyncio.sleep(0.2)
            return GetTaskResult(taskId=task_id, status="submitted", pollInterval=100)

        mock_session.get_task.side_effect = slow_get_task

        pending = PendingRequest(
            session=mock_session,
            task_created_handle=task_created(),
            result_handle=get_result(),
            result_type=CallToolResult,
            task_id="task-5",
        )

        # Trigger task created and direct result quickly
        async def complete_directly():
            await asyncio.sleep(0.01)
            task_created_event.set()
            await asyncio.sleep(0.01)
            result_event.set()

        asyncio.create_task(complete_directly())

        result = await pending.result()
        assert result == sample_result
        # get_task_result should not be called when direct path wins
        mock_session.get_task_result.assert_not_called()

    @pytest.mark.anyio
    async def test_task_polling_wins_race(self, mock_session: MagicMock, sample_result: CallToolResult):
        """Test that task polling path can complete before direct result."""
        task_created_event = asyncio.Event()
        task_created_event.set()

        async def task_created():
            pass

        async def never_completes():
            await asyncio.Future()  # Never completes
            return sample_result

        # Set up task polling to complete quickly
        mock_session.get_task.return_value = GetTaskResult(taskId="task-6", status="completed", pollInterval=100)
        mock_session.get_task_result.return_value = sample_result

        pending = PendingRequest(
            session=mock_session,
            task_created_handle=task_created(),
            result_handle=never_completes(),
            result_type=CallToolResult,
            task_id="task-6",
        )

        result = await pending.result()
        assert result == sample_result
        mock_session.get_task.assert_called_once_with("task-6")
        mock_session.get_task_result.assert_called_once_with("task-6", CallToolResult)


class TestPendingRequestErrorHandling:
    """Tests for error propagation and handling."""

    @pytest.mark.anyio
    async def test_error_from_direct_result_path(self, mock_session: MagicMock):
        """Test that errors from direct result path are propagated."""
        result_event = asyncio.Event()
        task_created_event = asyncio.Event()

        async def task_created():
            await task_created_event.wait()

        async def get_result_with_error():
            await result_event.wait()
            raise RuntimeError("Direct result failed")

        # Mock get_task to also fail after a delay, so both paths fail
        async def slow_get_task(task_id: str):
            await asyncio.sleep(0.1)
            raise RuntimeError("Task polling also failed")

        mock_session.get_task.side_effect = slow_get_task

        pending = PendingRequest(
            session=mock_session,
            task_created_handle=task_created(),
            result_handle=get_result_with_error(),
            result_type=CallToolResult,
            task_id="task-7",
        )

        # Trigger task created and error
        async def trigger_error():
            await asyncio.sleep(0.01)
            task_created_event.set()
            await asyncio.sleep(0.01)
            result_event.set()

        asyncio.create_task(trigger_error())

        with pytest.raises(RuntimeError, match="Direct result failed"):
            await pending.result()

    @pytest.mark.anyio
    async def test_error_from_task_polling_path(self, mock_session: MagicMock, sample_result: CallToolResult):
        """Test that errors from task polling are propagated."""
        task_created_event = asyncio.Event()
        task_created_event.set()

        async def task_created():
            pass

        async def slow_result_with_error():
            await asyncio.sleep(0.1)  # Takes longer than task polling error
            raise RuntimeError("Direct result also failed")

        # Set up task polling to fail immediately
        mock_session.get_task.side_effect = RuntimeError("Task polling failed")

        pending = PendingRequest(
            session=mock_session,
            task_created_handle=task_created(),
            result_handle=slow_result_with_error(),
            result_type=CallToolResult,
            task_id="task-8",
        )

        with pytest.raises(RuntimeError, match="Task polling failed"):
            await pending.result()

    @pytest.mark.anyio
    async def test_error_from_task_result_retrieval(self, mock_session: MagicMock, sample_result: CallToolResult):
        """Test that errors from get_task_result are propagated."""
        task_created_event = asyncio.Event()
        task_created_event.set()

        async def task_created():
            pass

        async def slow_result_with_error():
            await asyncio.sleep(0.1)  # Takes longer than result retrieval error
            raise RuntimeError("Direct result also failed")

        # Task polling succeeds but result retrieval fails
        mock_session.get_task.return_value = GetTaskResult(taskId="task-9", status="completed", pollInterval=100)
        mock_session.get_task_result.side_effect = RuntimeError("Failed to retrieve result")

        pending = PendingRequest(
            session=mock_session,
            task_created_handle=task_created(),
            result_handle=slow_result_with_error(),
            result_type=CallToolResult,
            task_id="task-9",
        )

        with pytest.raises(RuntimeError, match="Failed to retrieve result"):
            await pending.result()


class TestPendingRequestCancellation:
    """Tests for proper cleanup when pending requests are cancelled."""

    @pytest.mark.anyio
    async def test_cancellation_during_polling(self, mock_session: MagicMock, sample_result: CallToolResult):
        """Test that cancelling result() properly cleans up tasks."""
        task_created_event = asyncio.Event()
        task_created_event.set()

        async def task_created():
            pass

        async def never_completes():
            await asyncio.Future()  # Never completes
            return sample_result

        # Set up task polling to never complete
        async def never_complete_get_task(task_id: str):
            await asyncio.sleep(10)
            return GetTaskResult(taskId=task_id, status="submitted", pollInterval=100)

        mock_session.get_task.side_effect = never_complete_get_task

        pending = PendingRequest(
            session=mock_session,
            task_created_handle=task_created(),
            result_handle=never_completes(),
            result_type=CallToolResult,
            task_id="task-10",
        )

        # Create task and cancel it after a short delay
        result_task = asyncio.create_task(pending.result())
        await asyncio.sleep(0.05)
        result_task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await result_task

    @pytest.mark.anyio
    async def test_losing_path_is_cancelled(self, mock_session: MagicMock, sample_result: CallToolResult):
        """Test that the losing path in the race is properly cancelled."""
        task_created_event = asyncio.Event()
        result_event = asyncio.Event()

        async def task_created():
            await task_created_event.wait()

        async def get_result():
            await result_event.wait()
            return sample_result

        # Track if get_task is cancelled
        get_task_cancelled = False

        async def cancellable_get_task(task_id: str):
            nonlocal get_task_cancelled
            try:
                await asyncio.sleep(10)  # Will be cancelled
                return GetTaskResult(taskId=task_id, status="submitted", pollInterval=100)
            except asyncio.CancelledError:
                get_task_cancelled = True
                raise

        mock_session.get_task.side_effect = cancellable_get_task

        pending = PendingRequest(
            session=mock_session,
            task_created_handle=task_created(),
            result_handle=get_result(),
            result_type=CallToolResult,
            task_id="task-11",
        )

        # Set up direct result to win quickly
        async def complete_directly():
            await asyncio.sleep(0.01)
            task_created_event.set()
            await asyncio.sleep(0.01)
            result_event.set()

        asyncio.create_task(complete_directly())

        result = await pending.result()
        assert result == sample_result

        # Give cancellation time to propagate
        await asyncio.sleep(0.1)
        assert get_task_cancelled


class TestPendingRequestStatusTransitions:
    """Tests for various task status transition scenarios."""

    @pytest.mark.anyio
    async def test_immediate_completion(self, mock_session: MagicMock, sample_result: CallToolResult):
        """Test task that is already completed on first poll."""
        task_created_event = asyncio.Event()
        task_created_event.set()

        async def task_created():
            pass

        async def never_completes():
            await asyncio.Future()  # Never completes
            return sample_result

        mock_session.get_task.return_value = GetTaskResult(taskId="task-12", status="completed", pollInterval=100)
        mock_session.get_task_result.return_value = sample_result

        pending = PendingRequest(
            session=mock_session,
            task_created_handle=task_created(),
            result_handle=never_completes(),
            result_type=CallToolResult,
            task_id="task-12",
        )

        result = await pending.result()
        assert result == sample_result
        # Should only poll once
        mock_session.get_task.assert_called_once_with("task-12")

    @pytest.mark.anyio
    async def test_failed_status(self, mock_session: MagicMock, sample_result: CallToolResult):
        """Test task that transitions to failed status."""
        task_created_event = asyncio.Event()
        task_created_event.set()

        async def task_created():
            pass

        async def never_completes():
            await asyncio.Future()  # Never completes
            return sample_result

        mock_session.get_task.side_effect = [
            GetTaskResult(taskId="task-13", status="submitted", pollInterval=50),
            GetTaskResult(taskId="task-13", status="failed", pollInterval=50, error="Something went wrong"),
        ]
        mock_session.get_task_result.return_value = sample_result

        pending = PendingRequest(
            session=mock_session,
            task_created_handle=task_created(),
            result_handle=never_completes(),
            task_id="task-13",
            result_type=CallToolResult,
        )

        # Failed is a terminal state, so it should stop polling and retrieve result
        result = await pending.result()
        assert result == sample_result
        assert mock_session.get_task.call_count == 2

    @pytest.mark.anyio
    async def test_cancelled_status(self, mock_session: MagicMock, sample_result: CallToolResult):
        """Test task that transitions to cancelled status."""
        task_created_event = asyncio.Event()
        task_created_event.set()

        async def task_created():
            pass

        async def never_completes():
            await asyncio.Future()  # Never completes
            return sample_result

        mock_session.get_task.side_effect = [
            GetTaskResult(taskId="task-14", status="working", pollInterval=50),
            GetTaskResult(taskId="task-14", status="cancelled", pollInterval=50, error="User cancelled"),
        ]
        mock_session.get_task_result.return_value = sample_result

        pending = PendingRequest(
            session=mock_session,
            task_created_handle=task_created(),
            result_handle=never_completes(),
            result_type=CallToolResult,
            task_id="task-14",
        )

        # Cancelled is a terminal state
        result = await pending.result()
        assert result == sample_result
        assert mock_session.get_task.call_count == 2
