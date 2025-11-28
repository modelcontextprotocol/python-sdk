"""Tests for poll_task async iterator."""

from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest

from mcp.client.experimental.tasks import ExperimentalClientFeatures
from mcp.types import GetTaskResult, TaskStatus


def make_task_result(
    status: TaskStatus = "working",
    poll_interval: int = 0,
    task_id: str = "test-task",
    status_message: str | None = None,
) -> GetTaskResult:
    """Create GetTaskResult with sensible defaults."""
    now = datetime.now(timezone.utc)
    return GetTaskResult(
        taskId=task_id,
        status=status,
        statusMessage=status_message,
        createdAt=now,
        lastUpdatedAt=now,
        ttl=60000,
        pollInterval=poll_interval,
    )


def make_status_sequence(
    *statuses: TaskStatus,
    task_id: str = "test-task",
) -> Callable[[str], Coroutine[Any, Any, GetTaskResult]]:
    """Create mock get_task that returns statuses in sequence."""
    status_iter = iter(statuses)

    async def mock_get_task(tid: str) -> GetTaskResult:
        return make_task_result(status=next(status_iter), task_id=tid)

    return mock_get_task


@pytest.fixture
def mock_session() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def features(mock_session: AsyncMock) -> ExperimentalClientFeatures:
    return ExperimentalClientFeatures(mock_session)


@pytest.mark.anyio
async def test_poll_task_yields_until_completed(features: ExperimentalClientFeatures) -> None:
    """poll_task yields each status until terminal."""
    features.get_task = make_status_sequence("working", "working", "completed")  # type: ignore[method-assign]

    statuses = [s.status async for s in features.poll_task("test-task")]

    assert statuses == ["working", "working", "completed"]


@pytest.mark.anyio
@pytest.mark.parametrize("terminal_status", ["completed", "failed", "cancelled"])
async def test_poll_task_exits_on_terminal(features: ExperimentalClientFeatures, terminal_status: TaskStatus) -> None:
    """poll_task exits immediately when task is already terminal."""
    features.get_task = make_status_sequence(terminal_status)  # type: ignore[method-assign]

    statuses = [s.status async for s in features.poll_task("test-task")]

    assert statuses == [terminal_status]


@pytest.mark.anyio
async def test_poll_task_continues_through_input_required(features: ExperimentalClientFeatures) -> None:
    """poll_task yields input_required and continues (non-terminal)."""
    features.get_task = make_status_sequence("working", "input_required", "working", "completed")  # type: ignore[method-assign]

    statuses = [s.status async for s in features.poll_task("test-task")]

    assert statuses == ["working", "input_required", "working", "completed"]


@pytest.mark.anyio
async def test_poll_task_passes_task_id(features: ExperimentalClientFeatures) -> None:
    """poll_task passes correct task_id to get_task."""
    received_ids: list[str] = []

    async def mock_get_task(task_id: str) -> GetTaskResult:
        received_ids.append(task_id)
        return make_task_result(status="completed", task_id=task_id)

    features.get_task = mock_get_task  # type: ignore[method-assign]

    _ = [s async for s in features.poll_task("my-task-123")]

    assert received_ids == ["my-task-123"]


@pytest.mark.anyio
async def test_poll_task_yields_full_result(features: ExperimentalClientFeatures) -> None:
    """poll_task yields complete GetTaskResult objects."""

    async def mock_get_task(task_id: str) -> GetTaskResult:
        return make_task_result(
            status="completed",
            task_id=task_id,
            status_message="All done!",
        )

    features.get_task = mock_get_task  # type: ignore[method-assign]

    results = [r async for r in features.poll_task("test-task")]

    assert len(results) == 1
    assert results[0].status == "completed"
    assert results[0].statusMessage == "All done!"
    assert results[0].taskId == "test-task"
