"""Tasks extension (`io.modelcontextprotocol/tasks`).

Tasks let a client request *task-augmented* execution of a tool call: instead of
blocking for the `CallToolResult`, the client sends `tools/call` with a `task`
field and immediately gets back a `CreateTaskResult` carrying a task id. It then
polls `tasks/get` for status and `tasks/result` for the payload, and may
`tasks/cancel` or `tasks/list`. Tasks were part of the core spec in 2025-11-25
and now continue as an extension. See SEP-2133 for the extension framework.

This module demonstrates the *interceptive* half of the extension API. A `Tasks`
instance:

  - overrides `intercept_tool_call` to branch on `params.task`: a call WITHOUT a
    `task` field passes through untouched (it is a normal blocking call), so
    plain `tools/call` behaviour is unchanged. Only a call the client explicitly
    augments with a `task` field is recorded under a task id and returned with
    that id stamped into `_meta["io.modelcontextprotocol/related-task"]`, and
  - overrides `methods` to serve `tasks/get`, `tasks/result`, `tasks/cancel`,
    and `tasks/list` so a client can poll status and fetch the payload.

    mcp = MCPServer("demo", extensions=[Tasks()])

Scope: this is a reference implementation for the extension API, not a
production task runtime. Two deliberate simplifications keep it self-contained:

  - The tool runs to completion inline, so a task is observed as `completed`
    immediately (no detached/background execution, no TTL eviction).
  - Any tool may be task-augmented when the client sends a `task` field; per-tool
    gating on the declared `ToolExecution.task_support`
    (`forbidden`/`optional`/`required`) is not enforced. A production extension
    would reject a `task`-augmented call to a `forbidden` tool and a plain call
    to a `required` one.
  - A task-augmented `tools/call` returns a normal `CallToolResult` (with the
    task id in `_meta`) rather than the spec's `CreateTaskResult`. The wire
    schema for `tools/call` only admits `CallToolResult | InputRequiredResult`
    (even at 2026-07-28; see the `TODO(L56)` in `mcp.server.runner`), so
    returning `CreateTaskResult` would require extending the methods-layer
    validation maps. Driving the lifecycle through the dedicated `tasks/*`
    methods stays within the schema while still exercising the interceptor.

The store is in-memory and per-server.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import mcp_types as types

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver.extension import Extension, MethodBinding
from mcp.shared.exceptions import MCPError

EXTENSION_ID = "io.modelcontextprotocol/tasks"
"""The Tasks extension identifier."""

RELATED_TASK_META_KEY = "io.modelcontextprotocol/related-task"
"""`_meta` key associating a `CallToolResult` with the task that produced it."""

Clock = Callable[[], str]
"""Returns the current time as an ISO-8601 string (injectable for determinism)."""


def _fixed_clock() -> str:
    return "1970-01-01T00:00:00Z"


class TaskStore:
    """In-memory record of tasks and their completed payloads."""

    def __init__(self) -> None:
        self._tasks: dict[str, types.Task] = {}
        self._results: dict[str, dict[str, Any]] = {}
        self._counter = 0

    def create(self, now: str, ttl: int | None) -> types.Task:
        self._counter += 1
        task_id = f"task-{self._counter}"
        task = types.Task(
            task_id=task_id,
            status="working",
            created_at=now,
            last_updated_at=now,
            ttl=ttl,
        )
        self._tasks[task_id] = task
        return task

    def complete(self, task_id: str, now: str, result: dict[str, Any]) -> None:
        task = self._tasks[task_id]
        self._tasks[task_id] = task.model_copy(update={"status": "completed", "last_updated_at": now})
        self._results[task_id] = result

    def fail(self, task_id: str, now: str) -> None:
        task = self._tasks[task_id]
        self._tasks[task_id] = task.model_copy(update={"status": "failed", "last_updated_at": now})

    def cancel(self, task_id: str, now: str) -> types.Task:
        task = self._tasks[task_id]
        cancelled = task.model_copy(update={"status": "cancelled", "last_updated_at": now})
        self._tasks[task_id] = cancelled
        return cancelled

    def get(self, task_id: str) -> types.Task | None:
        return self._tasks.get(task_id)

    def result(self, task_id: str) -> dict[str, Any] | None:
        return self._results.get(task_id)

    def list(self) -> list[types.Task]:
        return list(self._tasks.values())


class Tasks(Extension):
    """The Tasks extension: task-augmented tool execution plus the `tasks/*` methods."""

    identifier = EXTENSION_ID

    def __init__(self, *, clock: Clock = _fixed_clock) -> None:
        self._store = TaskStore()
        self._clock = clock

    def settings(self) -> dict[str, Any]:
        # Advertise list + cancel support (per ServerTasksCapability).
        return {"list": {}, "cancel": {}}

    def methods(self) -> Sequence[MethodBinding]:
        return [
            MethodBinding("tasks/get", types.GetTaskRequestParams, self._handle_get),
            MethodBinding("tasks/result", types.GetTaskPayloadRequestParams, self._handle_result),
            MethodBinding("tasks/cancel", types.CancelTaskRequestParams, self._handle_cancel),
            MethodBinding("tasks/list", types.PaginatedRequestParams, self._handle_list),
        ]

    async def intercept_tool_call(
        self,
        params: types.CallToolRequestParams,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        if params.task is None:
            return await call_next(ctx)
        now = self._clock()
        task = self._store.create(now, params.task.ttl)
        # `call_next` runs the real tool; its already-serialized `CallToolResult`
        # dict is what we record and return (with the task id stamped on `_meta`).
        result = await call_next(ctx)
        payload = result if isinstance(result, dict) else {}
        if payload.get("isError"):
            self._store.fail(task.task_id, self._clock())
        else:
            self._store.complete(task.task_id, self._clock(), payload)
        existing_meta: dict[str, Any] = payload.get("_meta") or {}
        meta = {**existing_meta, RELATED_TASK_META_KEY: {"taskId": task.task_id}}
        return {**payload, "_meta": meta}

    async def _handle_get(
        self, ctx: ServerRequestContext[Any, Any], params: types.GetTaskRequestParams
    ) -> types.GetTaskResult:
        task = self._require(params.task_id)
        return types.GetTaskResult.model_validate(task.model_dump(by_alias=True))

    async def _handle_result(
        self, ctx: ServerRequestContext[Any, Any], params: types.GetTaskPayloadRequestParams
    ) -> dict[str, Any]:
        self._require(params.task_id)
        payload = self._store.result(params.task_id)
        if payload is None:
            raise MCPError(code=types.INVALID_PARAMS, message=f"task {params.task_id!r} has no result")
        return payload

    async def _handle_cancel(
        self, ctx: ServerRequestContext[Any, Any], params: types.CancelTaskRequestParams
    ) -> types.CancelTaskResult:
        self._require(params.task_id)
        cancelled = self._store.cancel(params.task_id, self._clock())
        return types.CancelTaskResult.model_validate(cancelled.model_dump(by_alias=True))

    async def _handle_list(
        self, ctx: ServerRequestContext[Any, Any], params: types.PaginatedRequestParams
    ) -> types.ListTasksResult:
        return types.ListTasksResult(tasks=self._store.list())

    def _require(self, task_id: str) -> types.Task:
        task = self._store.get(task_id)
        if task is None:
            raise MCPError(code=types.INVALID_PARAMS, message=f"unknown task {task_id!r}")
        return task
