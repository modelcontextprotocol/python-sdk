"""Tasks extension (`io.modelcontextprotocol/tasks`, SEP-2663).

Tasks let a server defer the result of a `tools/call`: instead of blocking for the
`CallToolResult`, the server immediately returns a `CreateTaskResult` carrying a
task id, and the client polls `tasks/get` for status and the eventual result.

SEP-2663 (https://modelcontextprotocol.io/seps/2663-tasks-extension.md) is an
opt-in extension, wire-incompatible with the 2025-11-25 in-core Tasks design that
still ships (types-only) in `mcp_types`. This module therefore defines its own
SEP-2663-shaped models rather than reusing `mcp_types.{Task, CreateTaskResult, ...}`.

Key SEP-2663 rules implemented here:

  - The SERVER decides task augmentation, per request, at its discretion. The
    legacy `params.task` field is ignored (it is not the opt-in).
  - A `CreateTaskResult` is only returned to a client that declared the extension
    on the request; a `tasks/*` call from a client that did not declare it is
    rejected with `-32003` (missing required client capability).
  - `CreateTaskResult` is `Result & Task` flat, with `resultType: "task"`.
  - `tasks/get` returns a `DetailedTask` (`resultType: "complete"`): `working`,
    `completed` (inlines the original `CallToolResult`), or `cancelled` here.
  - A tool result with `isError: true` is a `completed` task, not `failed`
    (`failed` is reserved for JSON-RPC errors).
  - `tasks/cancel` is an empty acknowledgement.

Scope: this is the conformant *core*. Deferred to follow-ups (each needs deeper
SDK plumbing): `tasks/update` + the MRTR `input_required` loop,
`ToolExecution.taskSupport` gating with the `-32021` required-task error,
`notifications/tasks`, and SEP-2243 task routing headers. The task runs to
completion inline, so it is observed as `completed` immediately; the store is
in-memory and per-server.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Sequence
from typing import Any, Literal

from mcp_types import INVALID_PARAMS, RequestParams, Result
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.extension import Extension, MethodBinding
from mcp.shared.exceptions import MCPError

EXTENSION_ID = "io.modelcontextprotocol/tasks"
"""The Tasks extension identifier (SEP-2663)."""

MISSING_REQUIRED_CLIENT_CAPABILITY = -32003
"""JSON-RPC error code: a `tasks/*` call from a client that did not declare the extension."""

TaskStatus = Literal["working", "input_required", "completed", "failed", "cancelled"]

Clock = Callable[[], str]
"""Returns the current time as an ISO-8601 string (injectable for determinism)."""


def _fixed_clock() -> str:
    return "1970-01-01T00:00:00Z"


class _TasksModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Task(_TasksModel):
    """SEP-2663 task snapshot (note the `*Ms` field names, unlike the 2025 design)."""

    task_id: str
    status: TaskStatus
    status_message: str | None = None
    created_at: str
    last_updated_at: str
    ttl_ms: int | None = None
    poll_interval_ms: int | None = None


class CreateTaskResult(Result):
    """`Result & Task` flat, discriminated by `result_type: "task"` (SEP-2663).

    Inherits `Result`'s camelCase alias generator, so snake_case fields serialize
    to `resultType`/`taskId`/`ttlMs`/... on the wire.
    """

    result_type: Literal["task"] = "task"
    task_id: str
    status: TaskStatus
    status_message: str | None = None
    created_at: str
    last_updated_at: str
    ttl_ms: int | None = None
    poll_interval_ms: int | None = None


def _task_envelope(task: Task) -> dict[str, Any]:
    return task.model_dump(by_alias=True, exclude_none=True)


class GetTaskRequestParams(RequestParams):
    task_id: str


class CancelTaskRequestParams(RequestParams):
    task_id: str


class TaskStore:
    """In-memory record of tasks and their completed `CallToolResult` payloads."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._results: dict[str, dict[str, Any]] = {}

    def create(self, now: str, ttl_ms: int | None) -> Task:
        # Task IDs are bearer capabilities for tasks/get|cancel, so they need
        # entropy a third party cannot guess or enumerate (SEP-2663 security).
        task_id = f"task_{secrets.token_urlsafe(16)}"
        task = Task(task_id=task_id, status="working", created_at=now, last_updated_at=now, ttl_ms=ttl_ms)
        self._tasks[task_id] = task
        return task

    def complete(self, task_id: str, now: str, result: dict[str, Any]) -> None:
        task = self._tasks[task_id]
        self._tasks[task_id] = task.model_copy(update={"status": "completed", "last_updated_at": now})
        self._results[task_id] = result

    def cancel(self, task_id: str, now: str) -> None:
        task = self._tasks[task_id]
        self._tasks[task_id] = task.model_copy(update={"status": "cancelled", "last_updated_at": now})

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def result(self, task_id: str) -> dict[str, Any] | None:
        return self._results.get(task_id)


class Tasks(Extension):
    """The Tasks extension: server-decided task-augmented `tools/call` plus `tasks/*`."""

    identifier = EXTENSION_ID

    def __init__(self, *, clock: Clock = _fixed_clock, default_ttl_ms: int | None = None) -> None:
        self._store = TaskStore()
        self._clock = clock
        self._default_ttl_ms = default_ttl_ms

    def methods(self) -> Sequence[MethodBinding]:
        return [
            MethodBinding("tasks/get", GetTaskRequestParams, self._handle_get),
            MethodBinding("tasks/cancel", CancelTaskRequestParams, self._handle_cancel),
        ]

    async def intercept_tool_call(
        self,
        params: Any,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        # SEP-2663: the server decides augmentation; the legacy `params.task` field
        # is ignored. Only augment for a client that declared the extension on the
        # request, and never alter a plain (non-declaring) client's call.
        if not _client_declared_tasks(ctx):
            return await call_next(ctx)
        now = self._clock()
        task = self._store.create(now, self._default_ttl_ms)
        result = await call_next(ctx)
        payload = result if isinstance(result, dict) else {}
        # A tool result (even isError: true) is a completed task; `failed` is for
        # JSON-RPC errors, which surface as a raised MCPError, not a result here.
        self._store.complete(task.task_id, self._clock(), payload)
        created = self._store.get(task.task_id)
        assert created is not None
        return CreateTaskResult(
            task_id=created.task_id,
            status=created.status,
            created_at=created.created_at,
            last_updated_at=created.last_updated_at,
            ttl_ms=created.ttl_ms,
        )

    async def _handle_get(self, ctx: ServerRequestContext[Any, Any], params: GetTaskRequestParams) -> dict[str, Any]:
        _require_tasks_capability(ctx)
        task = self._require(params.task_id)
        detailed = _task_envelope(task)
        detailed["resultType"] = "complete"
        if task.status == "completed":
            # DetailedTask: a completed task inlines the original CallToolResult.
            result = self._store.result(task.task_id)
            assert result is not None
            detailed["result"] = result
        return detailed

    async def _handle_cancel(
        self, ctx: ServerRequestContext[Any, Any], params: CancelTaskRequestParams
    ) -> dict[str, Any]:
        _require_tasks_capability(ctx)
        self._require(params.task_id)
        self._store.cancel(params.task_id, self._clock())
        # An empty acknowledgement; cancellation is cooperative.
        return {"resultType": "complete"}

    def _require(self, task_id: str) -> Task:
        task = self._store.get(task_id)
        if task is None:
            raise MCPError(code=INVALID_PARAMS, message=f"unknown task {task_id!r}")
        return task


def _client_declared_tasks(ctx: ServerRequestContext[Any, Any]) -> bool:
    # The extension only exists on the modern (2026-07-28+) wire: a legacy
    # `initialize` cannot carry `capabilities.extensions` back to the client, so a
    # legacy connection must never be augmented even if the client's recorded
    # capabilities happen to include the identifier.
    if ctx.protocol_version not in MODERN_PROTOCOL_VERSIONS:
        return False
    client_params = ctx.session.client_params
    declared = client_params.capabilities.extensions if client_params else None
    return bool(declared and EXTENSION_ID in declared)


def _require_tasks_capability(ctx: ServerRequestContext[Any, Any]) -> None:
    """Reject a `tasks/*` call from a client that did not declare the extension (-32003)."""
    if not _client_declared_tasks(ctx):
        raise MCPError(
            code=MISSING_REQUIRED_CLIENT_CAPABILITY,
            message="Client did not declare the io.modelcontextprotocol/tasks extension",
            data={"requiredCapabilities": {"extensions": {EXTENSION_ID: {}}}},
        )
