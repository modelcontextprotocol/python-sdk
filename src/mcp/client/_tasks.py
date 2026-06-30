"""SEP-2663 client-side task polling driver.

When a server augments a `tools/call` into a task — a `CreateTaskResult` in
place of the `CallToolResult` — the client polls `tasks/get` until the task
reaches a terminal status and surfaces only the final result. SEP-2663 advises
exactly this shape: "existing code returning a fixed shape ... can transparently
drive the polling flow internally and surface only the final, completed result".
This module implements that loop as a pure function so it stays testable with
plain closures; `Client` builds the `get_task` closure over its session,
`ClientSession` stays mechanics-only (mirroring `_input_required`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, cast

import anyio
from mcp_types import CallToolResult, ClientRequest, ErrorData

from mcp.client.extension import ClaimContext, ClientExtension, ResultClaim
from mcp.shared.exceptions import MCPError
from mcp.shared.tasks import (
    EXTENSION_ID,
    CreateTaskResult,
    GetTaskRequest,
    GetTaskRequestParams,
    GetTaskResult,
)

DEFAULT_POLL_INTERVAL_SECONDS = 1.0
"""Poll cadence when neither the snapshot nor the `CreateTaskResult` carries `pollIntervalMs`.

SEP-2663 makes the hint optional and only says clients SHOULD honor it when
present; one second is the SDK's conservative default in its absence.
"""


class TaskFailedError(MCPError):
    """The task reached `failed`: a JSON-RPC error occurred during execution (SEP-2663).

    Carries the JSON-RPC error inlined on `tasks/get` as `code`/`message`/`data`,
    plus the snapshot's optional `statusMessage` diagnostic.
    """

    def __init__(self, error: ErrorData, status_message: str | None = None) -> None:
        super().__init__(code=error.code, message=error.message, data=error.data)
        self.status_message = status_message


class TaskCancelledError(RuntimeError):
    """The task reached `cancelled` before producing a result (SEP-2663)."""

    def __init__(self, task_id: str, status_message: str | None = None) -> None:
        detail = f": {status_message}" if status_message is not None else ""
        super().__init__(f"Task {task_id!r} was cancelled{detail}")
        self.task_id = task_id
        self.status_message = status_message


class TaskInputRequiredError(RuntimeError):
    """The task reached `input_required`, which this driver does not drive yet.

    SEP-2663's in-task input loop (fulfil `inputRequests` via `tasks/update`) is
    a deferred follow-up in this SDK. Drive it manually: poll with
    `mcp.shared.tasks.GetTaskRequest` and answer with
    `mcp.shared.tasks.UpdateTaskRequest` over `session.send_request`.
    """

    def __init__(self, task_id: str) -> None:
        super().__init__(
            f"Task {task_id!r} requires in-task input (status `input_required`); the SDK's automatic "
            "in-task input loop is not implemented yet. Drive it manually with the `mcp.shared.tasks` "
            "request wrappers (`GetTaskRequest`/`UpdateTaskRequest`) over `session.send_request`."
        )
        self.task_id = task_id


async def run_task_driver(
    created: CreateTaskResult,
    *,
    get_task: Callable[[str], Awaitable[GetTaskResult]],
    sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
) -> CallToolResult:
    """Poll a `CreateTaskResult` to its final `CallToolResult`.

    Polls `tasks/get` (via `get_task`) until the task reaches a terminal status.
    Between polls it honors the SEP-2663 `pollIntervalMs` hint: each non-terminal
    snapshot sleeps its own `poll_interval_ms`, falling back to the
    `CreateTaskResult`'s, then to `DEFAULT_POLL_INTERVAL_SECONDS`.

    The loop deliberately imposes no round cap or deadline of its own: SEP-2663
    tasks represent unbounded server-side work, so how long to wait is the
    caller's policy — cancel via an enclosing anyio cancel scope, or bound each
    `tasks/get` round with the session read timeout the `get_task` closure
    carries.

    Args:
        created: The `CreateTaskResult` the augmented request returned.
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
        snapshot = await get_task(created.task_id)
        if snapshot.status == "completed":
            if snapshot.result is None:
                raise RuntimeError(
                    f"Task {created.task_id!r} is `completed` but carries no `result` (SEP-2663 violation)"
                )
            return CallToolResult.model_validate(snapshot.result, by_name=False)
        if snapshot.status == "failed":
            if snapshot.error is None:
                raise RuntimeError(f"Task {created.task_id!r} is `failed` but carries no `error` (SEP-2663 violation)")
            raise TaskFailedError(ErrorData.model_validate(snapshot.error), snapshot.status_message)
        if snapshot.status == "cancelled":
            raise TaskCancelledError(created.task_id, snapshot.status_message)
        if snapshot.status == "input_required":
            raise TaskInputRequiredError(created.task_id)
        interval_ms = snapshot.poll_interval_ms if snapshot.poll_interval_ms is not None else created.poll_interval_ms
        await sleep(DEFAULT_POLL_INTERVAL_SECONDS if interval_ms is None else interval_ms / 1000)


class TasksExtension(ClientExtension):
    """SEP-2663 Tasks as a client extension.

    Declares `io.modelcontextprotocol/tasks` and claims the `task` resultType on
    `tools/call`: a `CreateTaskResult` is resolved by polling `tasks/get` to the
    final `CallToolResult` via `run_task_driver`.
    """

    identifier = EXTENSION_ID

    def claims(self) -> Sequence[ResultClaim[Any]]:
        return (ResultClaim(result_type="task", model=CreateTaskResult, resolve=_resolve_created_task),)


async def _resolve_created_task(created: CreateTaskResult, ctx: ClaimContext) -> CallToolResult:
    """Poll an SEP-2663 task to its final `CallToolResult` (the transparent flow).

    Each `tasks/get` round goes through `ctx.session.send_request`, so it carries
    the caller's per-request read timeout (falling back to the session read
    timeout) and the `Mcp-Name` routing header. `Client.call_tool` re-validates
    the returned result against the tool's output schema, exactly as on the
    direct path.
    """
    session = ctx.session

    async def get_task(task_id: str) -> GetTaskResult:
        request = GetTaskRequest(params=GetTaskRequestParams(task_id=task_id))
        return await session.send_request(
            cast("ClientRequest", request), GetTaskResult, request_read_timeout_seconds=ctx.read_timeout_seconds
        )

    return await run_task_driver(created, get_task=get_task)
