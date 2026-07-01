"""Unit tests for the SEP-2663 client-side tasks surface.

`run_task_driver` is pure: it takes the task id and initial interval hint plus
`get_task` / `sleep` closures and polls until a terminal snapshot. These tests
build those closures by hand (scripted snapshot lists, recording sleeps) so the
driver is exercised without a `ClientSession` and with zero real sleeps. The
typed session functions (`get_task`, `wait_task`, `update_task`, `cancel_task`)
are driven the same way through a recording `ClientSession` double. Non-terminal
(`working`) snapshots only exist here: the live server records tasks born
terminal, so the polling cadence is reachable only through fakes. Integration
against a real server lives in `tests/server/test_tasks.py`.
"""

import pickle
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast

import anyio
import pytest
from inline_snapshot import snapshot
from mcp_types import INVALID_PARAMS, CallToolResult, EmptyResult, ErrorData, TextContent

import mcp.client.tasks
from mcp.client.session import ClientSession
from mcp.client.tasks import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    TaskCancelledError,
    TaskError,
    TaskFailedError,
    TaskInputRequiredError,
    cancel_task,
    get_task,
    run_task_driver,
    update_task,
    wait_task,
)
from mcp.shared.exceptions import MCPError
from mcp.shared.tasks import (
    CancelTaskRequest,
    CreateTaskResult,
    GetTaskRequest,
    GetTaskResult,
    TaskStatus,
    UpdateTaskRequest,
)

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


class _FakeSession:
    """`ClientSession` double: records every `send_request` and serves canned results."""

    def __init__(self, results: list[Any]) -> None:
        self.sent: list[tuple[Any, Any, float | None]] = []
        self._results = results

    async def send_request(
        self, request: Any, result_type: Any, request_read_timeout_seconds: float | None = None
    ) -> Any:
        self.sent.append((request, result_type, request_read_timeout_seconds))
        return self._results.pop(0)


def _fake_session(*results: Any) -> tuple[ClientSession, _FakeSession]:
    fake = _FakeSession(list(results))
    return cast(ClientSession, fake), fake


async def test_first_poll_completed_returns_the_validated_call_tool_result() -> None:
    """SEP-2663: a `completed` snapshot inlines the original result; the driver
    validates it as a `CallToolResult` and returns without ever sleeping (the
    born-terminal server shape)."""
    get_task, polled = _scripted_get_task([_snapshot("completed", result=dict(_COMPLETED_RESULT))])
    sleep, slept = _recording_sleep()

    with anyio.fail_after(5):
        result = await run_task_driver("task_abc", None, get_task=get_task, sleep=sleep)

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
        result = await run_task_driver("task_abc", None, get_task=get_task, sleep=sleep)

    assert result.content == [TextContent(text="done")]
    assert polled == ["task_abc", "task_abc", "task_abc"]
    assert slept == [0.05, 0.075]


async def test_snapshot_without_interval_falls_back_to_the_initial_hint() -> None:
    """SDK-defined: a snapshot missing `pollIntervalMs` falls back to the hint the
    `CreateTaskResult` carried (the driver's `initial_interval_ms`)."""
    get_task, _ = _scripted_get_task([_snapshot("working"), _snapshot("completed", result=dict(_COMPLETED_RESULT))])
    sleep, slept = _recording_sleep()

    with anyio.fail_after(5):
        await run_task_driver("task_abc", 200, get_task=get_task, sleep=sleep)

    assert slept == [0.2]


async def test_no_interval_anywhere_falls_back_to_one_second() -> None:
    """SDK-defined: with no `pollIntervalMs` on the snapshot or the
    `CreateTaskResult`, the driver polls at `DEFAULT_POLL_INTERVAL_SECONDS`."""
    get_task, _ = _scripted_get_task([_snapshot("working"), _snapshot("completed", result=dict(_COMPLETED_RESULT))])
    sleep, slept = _recording_sleep()

    with anyio.fail_after(5):
        await run_task_driver("task_abc", None, get_task=get_task, sleep=sleep)

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
        result = await run_task_driver("task_abc", None, get_task=get_task, sleep=sleep)

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
    sleep, _ = _recording_sleep()

    with anyio.fail_after(5):
        with pytest.raises(TaskFailedError) as exc_info:
            await run_task_driver("task_abc", None, get_task=get_task, sleep=sleep)

    assert exc_info.value.code == INVALID_PARAMS
    assert exc_info.value.message == "bad input"
    assert exc_info.value.data == {"field": "text"}
    assert exc_info.value.status_message == "bad input"


async def test_failed_snapshot_without_error_is_a_protocol_violation() -> None:
    """SEP-2663: a `failed` task MUST include the `error` field; a server omitting
    it violated the extension and the driver refuses to synthesize an error."""
    get_task, _ = _scripted_get_task([_snapshot("failed")])
    sleep, _ = _recording_sleep()

    with anyio.fail_after(5):
        with pytest.raises(RuntimeError, match="no `error`"):
            await run_task_driver("task_abc", None, get_task=get_task, sleep=sleep)


async def test_cancelled_snapshot_raises_task_cancelled_error() -> None:
    """SEP-2663: a task MAY reach `cancelled`; the driver surfaces it as a typed
    error carrying the task id and `statusMessage`."""
    get_task, _ = _scripted_get_task([_snapshot("cancelled", status_message="operator stop")])
    sleep, _ = _recording_sleep()

    with anyio.fail_after(5):
        with pytest.raises(TaskCancelledError) as exc_info:
            await run_task_driver("task_abc", None, get_task=get_task, sleep=sleep)

    assert exc_info.value.task_id == "task_abc"
    assert exc_info.value.status_message == "operator stop"
    assert str(exc_info.value) == snapshot("Task 'task_abc' was cancelled: operator stop")


async def test_input_required_snapshot_raises_task_input_required_error() -> None:
    """SDK-defined: the SEP-2663 in-task input loop (`inputRequests` over
    `tasks/update`) is a deferred follow-up — the driver raises a typed error
    pointing at the manual `get_task`/`update_task` surface instead of stalling."""
    get_task, _ = _scripted_get_task([_snapshot("input_required")])
    sleep, _ = _recording_sleep()

    with anyio.fail_after(5):
        with pytest.raises(TaskInputRequiredError) as exc_info:
            await run_task_driver("task_abc", None, get_task=get_task, sleep=sleep)

    assert exc_info.value.task_id == "task_abc"
    assert "update_task" in str(exc_info.value)


async def test_completed_snapshot_without_result_is_a_protocol_violation() -> None:
    """SEP-2663: a `completed` task MUST include the `result` field; a server
    omitting it violated the extension."""
    get_task, _ = _scripted_get_task([_snapshot("completed")])
    sleep, _ = _recording_sleep()

    with anyio.fail_after(5):
        with pytest.raises(RuntimeError, match="no `result`"):
            await run_task_driver("task_abc", None, get_task=get_task, sleep=sleep)


def test_every_task_outcome_error_shares_the_task_error_base() -> None:
    """SDK-defined: `TaskFailedError`, `TaskCancelledError`, and
    `TaskInputRequiredError` all subclass `TaskError`, so one `except TaskError`
    handles any non-completion; `TaskFailedError` keeps its `MCPError` base for
    callers catching wire errors."""
    failed = TaskFailedError.__mro__
    assert TaskError in failed and MCPError in failed
    assert issubclass(TaskCancelledError, TaskError)
    assert issubclass(TaskInputRequiredError, TaskError)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(
            TaskFailedError(ErrorData(code=INVALID_PARAMS, message="bad input", data={"field": "text"}), "bad input"),
            id="failed",
        ),
        pytest.param(TaskCancelledError("task_abc", "operator stop"), id="cancelled"),
        pytest.param(TaskInputRequiredError("task_abc"), id="input_required"),
        pytest.param(TaskError("boom"), id="base"),
    ],
)
def test_task_errors_survive_a_pickle_round_trip(error: TaskError) -> None:
    """SDK-defined: the task errors are public API and must survive process
    boundaries — a pickle round trip preserves the type, every attribute, and
    the message. (`TaskError` itself is a plain `Exception` and needs no help.)"""
    restored = pickle.loads(pickle.dumps(error))

    assert type(restored) is type(error)
    assert restored.__dict__ == error.__dict__
    assert str(restored) == str(error)


async def test_get_task_sends_one_tasks_get_and_returns_the_typed_snapshot() -> None:
    """SDK-defined: `get_task` is a single `tasks/get` over `session.send_request`,
    threading the per-request read timeout and parsing the snapshot as
    `GetTaskResult`."""
    completed = _snapshot("completed", result=dict(_COMPLETED_RESULT))
    session, fake = _fake_session(completed)

    with anyio.fail_after(5):
        result = await get_task(session, "task_abc", read_timeout_seconds=2.5)

    assert result is completed
    (request, result_type, timeout) = fake.sent[0]
    assert isinstance(request, GetTaskRequest)
    assert request.params.task_id == "task_abc"
    assert result_type is GetTaskResult
    assert timeout == 2.5


async def test_wait_task_from_a_bare_id_polls_that_id_to_the_final_result() -> None:
    """SDK-defined: `wait_task` accepts a bare persisted task id — the
    resume-after-restart shape, where no `CreateTaskResult` survives — and polls
    it to the final `CallToolResult`, bounding each round with the caller's
    read timeout."""
    session, fake = _fake_session(_snapshot("completed", result=dict(_COMPLETED_RESULT)))

    with anyio.fail_after(5):
        result = await wait_task(session, "task_abc", read_timeout_seconds=7.5)

    assert result == snapshot(CallToolResult(content=[TextContent(text="done")]))
    assert [(request.params.task_id, timeout) for (request, _, timeout) in fake.sent] == [("task_abc", 7.5)]


async def test_wait_task_from_a_create_task_result_seeds_the_poll_interval_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SDK-defined: given the `CreateTaskResult`, `wait_task` seeds the driver with
    its `pollIntervalMs`, so a snapshot without its own hint sleeps the seeded
    interval (the sleep is faked by patching the module's `anyio`)."""
    sleep, slept = _recording_sleep()
    monkeypatch.setattr(mcp.client.tasks, "anyio", SimpleNamespace(sleep=sleep))
    session, _ = _fake_session(_snapshot("working"), _snapshot("completed", result=dict(_COMPLETED_RESULT)))

    with anyio.fail_after(5):
        result = await wait_task(session, _created(poll_interval_ms=200))

    assert result.content == [TextContent(text="done")]
    assert slept == [0.2]


@pytest.mark.parametrize(
    ("terminal", "expected"),
    [
        (_snapshot("failed", error={"code": INVALID_PARAMS, "message": "bad input"}), TaskFailedError),
        (_snapshot("cancelled"), TaskCancelledError),
        (_snapshot("input_required"), TaskInputRequiredError),
    ],
)
async def test_wait_task_surfaces_every_non_completion_as_a_task_error(
    terminal: GetTaskResult, expected: type[TaskError]
) -> None:
    """SDK-defined: `wait_task` raises the same typed errors as the transparent
    path, and every one of them is catchable as `TaskError`."""
    session, _ = _fake_session(terminal)

    with anyio.fail_after(5):
        with pytest.raises(TaskError) as exc_info:
            await wait_task(session, "task_abc")

    assert type(exc_info.value) is expected


async def test_update_task_hides_the_ack_and_returns_none() -> None:
    """SDK-defined: `update_task` sends `tasks/update` with the given
    `inputResponses` and swallows the empty acknowledgement."""
    session, fake = _fake_session(EmptyResult())

    with anyio.fail_after(5):
        outcome = await update_task(session, "task_abc", {"demo:confirm": {"value": 1}}, read_timeout_seconds=2.5)

    assert outcome is None
    (request, result_type, timeout) = fake.sent[0]
    assert isinstance(request, UpdateTaskRequest)
    assert request.params.task_id == "task_abc"
    assert request.params.input_responses == {"demo:confirm": {"value": 1}}
    assert result_type is EmptyResult
    assert timeout == 2.5


async def test_cancel_task_hides_the_ack_and_returns_none() -> None:
    """SDK-defined: `cancel_task` sends `tasks/cancel` and swallows the empty
    acknowledgement; whether cancellation took effect is `get_task`'s answer."""
    session, fake = _fake_session(EmptyResult())

    with anyio.fail_after(5):
        outcome = await cancel_task(session, "task_abc", read_timeout_seconds=2.5)

    assert outcome is None
    (request, result_type, timeout) = fake.sent[0]
    assert isinstance(request, CancelTaskRequest)
    assert request.params.task_id == "task_abc"
    assert result_type is EmptyResult
    assert timeout == 2.5
