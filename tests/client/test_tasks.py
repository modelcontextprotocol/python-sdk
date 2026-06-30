"""Unit tests for the SEP-2663 client-side task polling driver.

`run_task_driver` is pure: it takes the `CreateTaskResult` plus `get_task` /
`sleep` closures and polls until a terminal snapshot. These tests build those
closures by hand (scripted snapshot lists, recording sleeps) so the driver is
exercised without a `ClientSession` and with zero real sleeps. Non-terminal
(`working`) snapshots only exist here: the live server records tasks born
terminal, so the polling cadence is reachable only through fakes. Integration
against a real server lives in `tests/server/test_tasks.py`.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import anyio
import pytest
from inline_snapshot import snapshot
from mcp_types import INVALID_PARAMS, CallToolResult, TextContent

from mcp.client._tasks import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    TaskCancelledError,
    TaskFailedError,
    TaskInputRequiredError,
    run_task_driver,
)
from mcp.shared.tasks import CreateTaskResult, GetTaskResult, TaskStatus

pytestmark = pytest.mark.anyio

_STAMP = "2026-01-01T00:00:00Z"

_COMPLETED_RESULT: dict[str, Any] = {
    "content": [{"type": "text", "text": "done"}],
    "isError": False,
    "resultType": "complete",
}


def _created(*, poll_interval_ms: int | None = None) -> CreateTaskResult:
    return CreateTaskResult(
        task_id="task_abc",
        status="working",
        created_at=_STAMP,
        last_updated_at=_STAMP,
        poll_interval_ms=poll_interval_ms,
    )


def _snapshot(
    status: TaskStatus,
    *,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    status_message: str | None = None,
    poll_interval_ms: int | None = None,
) -> GetTaskResult:
    return GetTaskResult(
        task_id="task_abc",
        status=status,
        created_at=_STAMP,
        last_updated_at=_STAMP,
        result=result,
        error=error,
        status_message=status_message,
        poll_interval_ms=poll_interval_ms,
    )


def _scripted_get_task(
    snapshots: list[GetTaskResult],
) -> tuple[Callable[[str], Awaitable[GetTaskResult]], list[str]]:
    """A `get_task` closure serving canned snapshots in order, recording the polled ids."""
    polled: list[str] = []

    async def get_task(task_id: str) -> GetTaskResult:
        polled.append(task_id)
        return snapshots.pop(0)

    return get_task, polled


def _recording_sleep() -> tuple[Callable[[float], Awaitable[None]], list[float]]:
    """A `sleep` closure that records requested durations and returns immediately."""
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    return sleep, slept


async def test_first_poll_completed_returns_the_validated_call_tool_result() -> None:
    """SEP-2663: a `completed` snapshot inlines the original result; the driver
    validates it as a `CallToolResult` and returns without ever sleeping (the
    born-terminal server shape)."""
    get_task, polled = _scripted_get_task([_snapshot("completed", result=dict(_COMPLETED_RESULT))])
    sleep, slept = _recording_sleep()

    with anyio.fail_after(5):
        result = await run_task_driver(_created(), get_task=get_task, sleep=sleep)

    assert result == snapshot(CallToolResult(content=[TextContent(text="done")]))
    assert polled == ["task_abc"]
    assert slept == []


async def test_working_snapshots_sleep_their_own_poll_interval_before_repolling() -> None:
    """SEP-2663: clients SHOULD honor `pollIntervalMs`, which MAY change over the
    task's lifetime — each `working` snapshot's own hint governs the next sleep."""
    get_task, polled = _scripted_get_task(
        [
            _snapshot("working", poll_interval_ms=50),
            _snapshot("working", poll_interval_ms=75),
            _snapshot("completed", result=dict(_COMPLETED_RESULT)),
        ]
    )
    sleep, slept = _recording_sleep()

    with anyio.fail_after(5):
        result = await run_task_driver(_created(), get_task=get_task, sleep=sleep)

    assert result.content == [TextContent(text="done")]
    assert polled == ["task_abc", "task_abc", "task_abc"]
    assert slept == [0.05, 0.075]


async def test_snapshot_without_interval_falls_back_to_the_create_task_results() -> None:
    """SDK-defined: a snapshot missing `pollIntervalMs` falls back to the hint the
    `CreateTaskResult` carried."""
    get_task, _ = _scripted_get_task([_snapshot("working"), _snapshot("completed", result=dict(_COMPLETED_RESULT))])
    sleep, slept = _recording_sleep()

    with anyio.fail_after(5):
        await run_task_driver(_created(poll_interval_ms=200), get_task=get_task, sleep=sleep)

    assert slept == [0.2]


async def test_no_interval_anywhere_falls_back_to_one_second() -> None:
    """SDK-defined: with no `pollIntervalMs` on the snapshot or the
    `CreateTaskResult`, the driver polls at `DEFAULT_POLL_INTERVAL_SECONDS`."""
    get_task, _ = _scripted_get_task([_snapshot("working"), _snapshot("completed", result=dict(_COMPLETED_RESULT))])
    sleep, slept = _recording_sleep()

    with anyio.fail_after(5):
        await run_task_driver(_created(), get_task=get_task, sleep=sleep)

    assert slept == [DEFAULT_POLL_INTERVAL_SECONDS] == [1.0]


async def test_negative_poll_interval_is_floored_to_zero() -> None:
    """SDK-defined: a misbehaving server's negative interval must not crash or
    busy-loop the driver — it is floored to a zero-length sleep."""
    get_task, _ = _scripted_get_task(
        [
            _snapshot("working", poll_interval_ms=-5000),
            _snapshot("completed", result=dict(_COMPLETED_RESULT)),
        ]
    )
    sleep, slept = _recording_sleep()

    with anyio.fail_after(5):
        result = await run_task_driver(_created(), get_task=get_task, sleep=sleep)

    assert result.content == [TextContent(text="done")]
    assert slept == [0.0]


async def test_failed_snapshot_raises_task_failed_error_with_code_and_status_message() -> None:
    """SEP-2663: a `failed` task inlines the JSON-RPC error and SHOULD carry a
    `statusMessage` diagnostic — both surface on the typed error."""
    failed = _snapshot(
        "failed",
        error={"code": INVALID_PARAMS, "message": "bad input", "data": {"field": "text"}},
        status_message="bad input",
    )
    get_task, _ = _scripted_get_task([failed])

    with anyio.fail_after(5):
        with pytest.raises(TaskFailedError) as exc_info:
            await run_task_driver(_created(), get_task=get_task)

    assert exc_info.value.code == INVALID_PARAMS
    assert exc_info.value.message == "bad input"
    assert exc_info.value.data == {"field": "text"}
    assert exc_info.value.status_message == "bad input"


async def test_failed_snapshot_without_error_is_a_protocol_violation() -> None:
    """SEP-2663: a `failed` task MUST include the `error` field; a server omitting
    it violated the extension and the driver refuses to synthesize an error."""
    get_task, _ = _scripted_get_task([_snapshot("failed")])

    with anyio.fail_after(5):
        with pytest.raises(RuntimeError, match="no `error`"):
            await run_task_driver(_created(), get_task=get_task)


async def test_cancelled_snapshot_raises_task_cancelled_error() -> None:
    """SEP-2663: a task MAY reach `cancelled`; the driver surfaces it as a typed
    error carrying the task id and `statusMessage`."""
    get_task, _ = _scripted_get_task([_snapshot("cancelled", status_message="operator stop")])

    with anyio.fail_after(5):
        with pytest.raises(TaskCancelledError) as exc_info:
            await run_task_driver(_created(), get_task=get_task)

    assert exc_info.value.task_id == "task_abc"
    assert exc_info.value.status_message == "operator stop"
    assert str(exc_info.value) == snapshot("Task 'task_abc' was cancelled: operator stop")


async def test_input_required_snapshot_raises_task_input_required_error() -> None:
    """SDK-defined: the SEP-2663 in-task input loop (`inputRequests` over
    `tasks/update`) is a deferred follow-up — the driver raises a typed error
    pointing at the manual `mcp.shared.tasks` surface instead of stalling."""
    get_task, _ = _scripted_get_task([_snapshot("input_required")])

    with anyio.fail_after(5):
        with pytest.raises(TaskInputRequiredError) as exc_info:
            await run_task_driver(_created(), get_task=get_task)

    assert exc_info.value.task_id == "task_abc"
    assert "UpdateTaskRequest" in str(exc_info.value)


async def test_completed_snapshot_without_result_is_a_protocol_violation() -> None:
    """SEP-2663: a `completed` task MUST include the `result` field; a server
    omitting it violated the extension."""
    get_task, _ = _scripted_get_task([_snapshot("completed")])

    with anyio.fail_after(5):
        with pytest.raises(RuntimeError, match="no `result`"):
            await run_task_driver(_created(), get_task=get_task)
