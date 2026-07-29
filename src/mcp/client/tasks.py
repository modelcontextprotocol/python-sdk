"""SEP-2663 client-side tasks surface.

When a server augments a `tools/call` into a task — a `CreateTaskResult` in
place of the `CallToolResult` — this module finishes the flow, twice over.
`TasksExtension` is the transparent path SEP-2663 advises ("existing code
returning a fixed shape ... can transparently drive the polling flow internally
and surface only the final, completed result"): `Client.call_tool` polls
`tasks/get` until the task reaches a terminal status and surfaces only the
final result. The free functions — `get_task`, `wait_task`, `update_task`,
`cancel_task` — are the manual path, typed over the public `ClientSession`,
for callers that take the `CreateTaskResult` themselves (via
`session.call_tool(..., allow_claimed=True)`) and drive `tasks/*` by hand.

The polling loop itself is one pure function (`run_task_driver`, private) so it
stays testable with plain closures; both paths run it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

import anyio
from mcp_types import CallToolResult, EmptyResult, ErrorData

from mcp.client.extension import ClaimContext, ClientExtension, ResultClaim
from mcp.shared.exceptions import MCPError
from mcp.shared.tasks import (
    EXTENSION_ID,
    CancelTaskRequest,
    CancelTaskRequestParams,
    CreateTaskResult,
    GetTaskRequest,
    GetTaskRequestParams,
    GetTaskResult,
    UpdateTaskRequest,
    UpdateTaskRequestParams,
)

if TYPE_CHECKING:
    from mcp.client.session import ClientSession

__all__ = [
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "TaskCancelledError",
    "TaskError",
    "TaskFailedError",
    "TaskInputRequiredError",
    "TasksExtension",
    "cancel_task",
    "get_task",
    "update_task",
    "wait_task",
]

DEFAULT_POLL_INTERVAL_SECONDS = 1.0
"""Poll cadence when neither the snapshot nor the `CreateTaskResult` carries `pollIntervalMs`.

SEP-2663 makes the hint optional and only says clients SHOULD honor it when
present; one second is the SDK's conservative default in its absence.
"""


class TaskError(Exception):
    """Base for the typed SEP-2663 task-outcome errors.

    A task that ends anywhere other than `completed` surfaces as one of three
    subclasses — `TaskFailedError`, `TaskCancelledError`,
    `TaskInputRequiredError` — so `except TaskError` handles any non-completion.
    """


class TaskFailedError(TaskError, MCPError):
    """The task reached `failed`: a JSON-RPC error occurred during execution (SEP-2663).

    Carries the JSON-RPC error inlined on `tasks/get` as `code`/`message`/`data`,
    plus the snapshot's optional `statusMessage` diagnostic.
    """

    def __init__(self, error: ErrorData, status_message: str | None = None) -> None:
        super().__init__(code=error.code, message=error.message, data=error.data)
        self.status_message = status_message

    def __reduce__(self) -> tuple[type[TaskFailedError], tuple[ErrorData, str | None]]:
        """Pickle via the constructor args (`args` holds `MCPError`'s, which do not round-trip)."""
        return (type(self), (self.error, self.status_message))


class TaskCancelledError(TaskError):
    """The task reached `cancelled` before producing a result (SEP-2663)."""

    def __init__(self, task_id: str, status_message: str | None = None) -> None:
        detail = f": {status_message}" if status_message is not None else ""
        super().__init__(f"Task {task_id!r} was cancelled{detail}")
        self.task_id = task_id
        self.status_message = status_message

    def __reduce__(self) -> tuple[type[TaskCancelledError], tuple[str, str | None]]:
        """Pickle via the constructor args (`args` holds the formatted message, which does not round-trip)."""
        return (type(self), (self.task_id, self.status_message))


class TaskInputRequiredError(TaskError):
    """The task reached `input_required`, which the polling loop does not drive yet.

    SEP-2663's in-task input loop (fulfil `inputRequests` via `tasks/update`) is
    a deferred follow-up in this SDK. Drive it manually: fetch the snapshot with
    `get_task` and answer its `inputRequests` with `update_task`.
    """

    def __init__(self, task_id: str) -> None:
        super().__init__(
            f"Task {task_id!r} requires in-task input (status `input_required`); the SDK's automatic "
            "in-task input loop is not implemented yet. Drive it manually: fetch the snapshot with "
            "`mcp.client.tasks.get_task` and answer with `mcp.client.tasks.update_task`."
        )
        self.task_id = task_id

    def __reduce__(self) -> tuple[type[TaskInputRequiredError], tuple[str]]:
        """Pickle via the constructor args (`args` holds the formatted message, which does not round-trip)."""
        return (type(self), (self.task_id,))


async def run_task_driver(
    task_id: str,
    initial_interval_ms: int | None,
    *,
    get_task: Callable[[str], Awaitable[GetTaskResult]],
    sleep: Callable[[float], Awaitable[None]],
) -> CallToolResult:
    """Poll a task to its final `CallToolResult` (the private engine behind both paths).

    Polls `tasks/get` (via `get_task`) until the task reaches a terminal status.
    Between polls it honors the SEP-2663 `pollIntervalMs` hint: each non-terminal
    snapshot sleeps its own `poll_interval_ms`, falling back to
    `initial_interval_ms` (the `CreateTaskResult`'s hint, when the caller holds
    one), then to `DEFAULT_POLL_INTERVAL_SECONDS`.

    The loop deliberately imposes no round cap or deadline of its own: SEP-2663
    tasks represent unbounded server-side work, so how long to wait is the
    caller's policy — cancel via an enclosing anyio cancel scope, or bound each
    `tasks/get` round with the session read timeout the `get_task` closure
    carries.

    Args:
        task_id: The task to poll.
        initial_interval_ms: `pollIntervalMs` from the `CreateTaskResult`, or
            `None` when the caller holds only a bare task id.
        get_task: Sends one `tasks/get` for the given task id and returns the
            parsed `GetTaskResult` snapshot.
        sleep: Awaits the given number of seconds between polls (injectable for
            deterministic tests).

    Raises:
        TaskFailedError: The task reached `failed`; carries the inlined JSON-RPC error.
        TaskCancelledError: The task reached `cancelled`.
        TaskInputRequiredError: The task reached `input_required` (the in-task
            input loop is not implemented yet).
        RuntimeError: The server violated SEP-2663 — a `completed` snapshot
            without `result`, or a `failed` snapshot without `error`.
    """
    while True:
        snapshot = await get_task(task_id)
        if snapshot.status == "completed":
            if snapshot.result is None:
                raise RuntimeError(f"Task {task_id!r} is `completed` but carries no `result` (SEP-2663 violation)")
            return CallToolResult.model_validate(snapshot.result, by_name=False)
        if snapshot.status == "failed":
            if snapshot.error is None:
                raise RuntimeError(f"Task {task_id!r} is `failed` but carries no `error` (SEP-2663 violation)")
            raise TaskFailedError(ErrorData.model_validate(snapshot.error), snapshot.status_message)
        if snapshot.status == "cancelled":
            raise TaskCancelledError(task_id, snapshot.status_message)
        if snapshot.status == "input_required":
            raise TaskInputRequiredError(task_id)
        interval_ms = snapshot.poll_interval_ms if snapshot.poll_interval_ms is not None else initial_interval_ms
        await sleep(DEFAULT_POLL_INTERVAL_SECONDS if interval_ms is None else max(0, interval_ms) / 1000)


async def get_task(
    session: ClientSession,
    task_id: str,
    *,
    read_timeout_seconds: float | None = None,
) -> GetTaskResult:
    """Fetch one SEP-2663 `tasks/get` snapshot.

    One request, one typed parse: the returned `GetTaskResult` carries `result`
    when the task `completed`, `error` when it `failed`, and neither for a
    non-terminal status.

    Args:
        session: The session to send on.
        task_id: The task id a `CreateTaskResult` carried.
        read_timeout_seconds: Per-request read timeout; defaults to the
            session's.

    Raises:
        MCPError: `-32602` (invalid params) for an unknown or expired task id,
            `-32021` (missing required client capability) when this modern
            client did not declare the extension, or `-32601` (method not
            found) on a legacy (2025-11-25) connection.
    """
    request = GetTaskRequest(params=GetTaskRequestParams(task_id=task_id))
    return await session.send_request(request, GetTaskResult, request_read_timeout_seconds=read_timeout_seconds)


async def wait_task(
    session: ClientSession,
    task: str | CreateTaskResult,
    *,
    read_timeout_seconds: float | None = None,
) -> CallToolResult:
    """Poll an SEP-2663 task to a terminal status and return its final `CallToolResult`.

    The manual counterpart of the transparent `TasksExtension` flow, raising the
    same typed errors. Pass the `CreateTaskResult` and its `pollIntervalMs` hint
    seeds the polling cadence; pass a bare task id and a client that reconnected
    — or restarted with only the persisted id — resumes a task it no longer
    holds the `CreateTaskResult` for.

    The wait itself is unbounded (how long to keep polling is the caller's
    policy — cancel via an enclosing anyio cancel scope);
    `read_timeout_seconds` bounds each `tasks/get` round, not the whole wait.

    Args:
        session: The session to poll on.
        task: The `CreateTaskResult` the augmented call returned, or a bare
            task id.
        read_timeout_seconds: Per-request read timeout for each `tasks/get`
            round; defaults to the session's.

    Raises:
        TaskFailedError: The task reached `failed`; carries the inlined JSON-RPC error.
        TaskCancelledError: The task reached `cancelled`.
        TaskInputRequiredError: The task reached `input_required` (the in-task
            input loop is not implemented yet).
        RuntimeError: The server violated SEP-2663 — a `completed` snapshot
            without `result`, or a `failed` snapshot without `error`.
        MCPError: A `tasks/get` round failed on the wire: `-32602` (invalid
            params) for an unknown or expired task id, `-32021` (missing
            required client capability) when this modern client did not declare
            the extension, or `-32601` (method not found) on a legacy
            (2025-11-25) connection.
    """
    if isinstance(task, str):
        task_id, initial_interval_ms = task, None
    else:
        task_id, initial_interval_ms = task.task_id, task.poll_interval_ms

    async def poll(task_id: str) -> GetTaskResult:
        return await get_task(session, task_id, read_timeout_seconds=read_timeout_seconds)

    return await run_task_driver(task_id, initial_interval_ms, get_task=poll, sleep=anyio.sleep)


async def update_task(
    session: ClientSession,
    task_id: str,
    input_responses: dict[str, Any],
    *,
    read_timeout_seconds: float | None = None,
) -> None:
    """Answer an SEP-2663 task's in-task input requests (`tasks/update`).

    `input_responses` maps keys of the snapshot's `inputRequests` to their
    answers; servers should ignore responses for keys the task never issued
    (SEP-2663).
    The server acknowledges with an empty result, which is swallowed.

    Args:
        session: The session to send on.
        task_id: The task id a `CreateTaskResult` carried.
        input_responses: Answers keyed by the snapshot's `inputRequests` keys.
        read_timeout_seconds: Per-request read timeout; defaults to the
            session's.

    Raises:
        MCPError: `-32602` (invalid params) for an unknown or expired task id,
            `-32021` (missing required client capability) when this modern
            client did not declare the extension, or `-32601` (method not
            found) on a legacy (2025-11-25) connection.
    """
    request = UpdateTaskRequest(params=UpdateTaskRequestParams(task_id=task_id, input_responses=input_responses))
    await session.send_request(request, EmptyResult, request_read_timeout_seconds=read_timeout_seconds)


async def cancel_task(
    session: ClientSession,
    task_id: str,
    *,
    read_timeout_seconds: float | None = None,
) -> None:
    """Request cancellation of an SEP-2663 task (`tasks/cancel`).

    Cancellation is cooperative and may never take effect: SEP-2663 lets the
    server finish the task anyway, and in this SDK the work has always finished
    before a `tasks/cancel` can arrive. The server acknowledges with an empty
    result, which is swallowed — follow with `get_task` to see the status that
    actually resulted.

    Args:
        session: The session to send on.
        task_id: The task id a `CreateTaskResult` carried.
        read_timeout_seconds: Per-request read timeout; defaults to the
            session's.

    Raises:
        MCPError: `-32602` (invalid params) for an unknown or expired task id,
            `-32021` (missing required client capability) when this modern
            client did not declare the extension, or `-32601` (method not
            found) on a legacy (2025-11-25) connection.
    """
    request = CancelTaskRequest(params=CancelTaskRequestParams(task_id=task_id))
    await session.send_request(request, EmptyResult, request_read_timeout_seconds=read_timeout_seconds)


class TasksExtension(ClientExtension):
    """SEP-2663 Tasks as a client extension.

    Declares `io.modelcontextprotocol/tasks` and claims the `task` resultType on
    `tools/call`: a `CreateTaskResult` is resolved by polling `tasks/get` to the
    final `CallToolResult`, exactly as `wait_task` does by hand.
    """

    identifier = EXTENSION_ID

    def claims(self) -> Sequence[ResultClaim[Any]]:
        return (ResultClaim(result_type="task", model=CreateTaskResult, resolve=_resolve_created_task),)


async def _resolve_created_task(created: CreateTaskResult, ctx: ClaimContext) -> CallToolResult:
    """Poll an SEP-2663 task to its final `CallToolResult` (the transparent flow).

    Delegates to `wait_task`, so each `tasks/get` round goes through
    `ctx.session.send_request` — carrying the caller's per-request read timeout
    (falling back to the session read timeout) and the `Mcp-Name` routing
    header. `Client.call_tool` re-validates the returned result against the
    tool's output schema, exactly as on the direct path.
    """
    return await wait_task(ctx.session, created, read_timeout_seconds=ctx.read_timeout_seconds)
