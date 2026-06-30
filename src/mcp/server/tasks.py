"""Tasks extension (`io.modelcontextprotocol/tasks`, SEP-2663).

Tasks let a server defer the result of a `tools/call`: instead of blocking for the
`CallToolResult`, the server immediately returns a `CreateTaskResult` carrying a
task id, and the client polls `tasks/get` for status and the eventual result.

SEP-2663 (https://modelcontextprotocol.io/seps/2663-tasks-extension.md) is an
opt-in extension, wire-incompatible with the 2025-11-25 in-core Tasks design that
still ships (types-only) in `mcp_types`. The SEP-2663-shaped wire models live in
`mcp.shared.tasks` (re-exported here); this module is the server runtime.

Key SEP-2663 rules implemented here:

  - The SERVER decides task augmentation, per request, at its discretion (the
    `Tasks(augment=...)` predicate). The legacy `params.task` field is ignored
    (it is not the opt-in).
  - A `CreateTaskResult` is only returned to a client that declared the extension
    on the request; a `tasks/*` call from a modern client that did not declare it
    is rejected with `MISSING_REQUIRED_CLIENT_CAPABILITY` (`-32021`), and a legacy
    (<= 2025-11-25) call gets `METHOD_NOT_FOUND` -- the extension is not defined on
    that wire.
  - `CreateTaskResult` is `Result & Task` flat, with `resultType: "task"`.
  - `tasks/get` returns the task (`resultType: "complete"`), inlining the original
    `CallToolResult` on a `completed` task or the JSON-RPC error on a `failed`
    one -- never both. A tool result with `isError: true` is a `completed` task;
    `failed` is reserved for JSON-RPC errors.
  - A multi round-trip interim (`resultType: "input_required"`) is passed through
    un-augmented: SEP-2663 resolves MRTR exchanges on the original `tools/call`
    before task creation, so only the leg that produces the final result becomes
    a task.
  - `tasks/cancel` and `tasks/update` are empty acknowledgements (`resultType:
    "complete"` is required on the ack). Cancellation is cooperative and may
    never take effect; updates for input requests that were never issued are
    ignored. Both are no-ops here by construction (see below).

Execution model: the tool runs to completion inside the interceptor, so a task is
born terminal, in {`completed`, `failed`} -- SEP-2663 allows any initial status
(the embedded task is "typically (though not necessarily)" `working`). A chain
that produces a result -- `isError: true` included -- records a `completed` task.
A chain that raises a JSON-RPC error (or a nested interceptor that returns
`ErrorData`) records a `failed` task carrying that error, and the declaring
client receives a `failed` `CreateTaskResult` instead of the JSON-RPC error;
`tasks/get` then inlines the error. A task exists only once its outcome exists:
there is no `working` state to corrupt and no terminal transition to guard, so
cancellation can still never take effect (terminal statuses are absorbing --
unchanged invariant). Errors propagate untouched on every non-augmented path: a
non-declaring client, a legacy connection, or an `augment` predicate that
excluded the call. Background execution (returning `working` tasks), the in-task
`input_required`/`inputResponses` loop over `tasks/update`, and
`notifications/tasks` over `subscriptions/listen` are deferred follow-ups, each
needing deeper SDK plumbing. (SEP-2663's `Mcp-Name: <taskId>` routing header --
the SEP-2243 header family -- is already handled by the shared header table in
`mcp.shared.inbound`.)

Task ids are unguessable bearer capabilities: any caller presenting a valid id
may poll the task. That is deliberate -- the modern wire has no sessions, and a
reconnecting client must be able to poll. Servers that need stricter scoping,
bounded retention without TTLs, or durable multi-worker storage supply their own
store via `Tasks(store=...)`; the in-memory default is per-process.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from mcp_types import INVALID_PARAMS, CallToolRequestParams, EmptyResult, ErrorData
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import BaseModel

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.extension import Extension, MethodBinding, require_client_extension
from mcp.shared.exceptions import MCPError
from mcp.shared.tasks import (
    EXTENSION_ID,
    CancelTaskRequestParams,
    CreateTaskResult,
    GetTaskRequestParams,
    Task,
    TaskStatus,
    UpdateTaskRequestParams,
)

__all__ = [
    "EXTENSION_ID",
    "CancelTaskRequestParams",
    "Clock",
    "CreateTaskResult",
    "GetTaskRequestParams",
    "InMemoryTaskStore",
    "Task",
    "TaskRecord",
    "TaskStatus",
    "TaskStore",
    "Tasks",
    "UpdateTaskRequestParams",
]

Clock = Callable[[], datetime]
"""Returns the current time as an aware UTC datetime (injectable for determinism)."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _wire_timestamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class TaskRecord:
    """What a `TaskStore` persists for one task.

    `task` is the wire snapshot; the outcome rides beside it, discriminated by
    `task.status`: a `completed` task stores the serialized `CallToolResult` in
    `result` (`error` is `None`), a `failed` task stores the JSON-RPC error dict
    in `error` (`result` is `None`). `expires_at` is the absolute deadline
    derived from `ttlMs` (`None` = never expires).
    """

    task: Task
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    expires_at: datetime | None


class TaskStore(Protocol):
    """Persistence seam for task records.

    SEP-2663 requires a task to be durably created before its `CreateTaskResult`
    is returned, so multi-worker deployments must back this with shared storage;
    the in-memory default is per-process.

    Contract: `get` returns `None` both for unknown ids and for records whose
    `expires_at` has passed -- a store enforces its records' TTLs the way an
    external store with native expiry would.
    """

    async def put(self, record: TaskRecord) -> None: ...

    async def get(self, task_id: str) -> TaskRecord | None: ...


class InMemoryTaskStore:
    """Per-process `TaskStore` for stdio servers and single-process development.

    Expired records are dropped on access and swept on every `put`, so the store
    only retains live tasks. Tasks without a TTL are retained for the store's
    lifetime -- configure `Tasks(default_ttl_ms=...)` to bound retention.
    """

    def __init__(self, *, clock: Clock = _utc_now) -> None:
        self._clock = clock
        self._records: dict[str, TaskRecord] = {}

    async def put(self, record: TaskRecord) -> None:
        now = self._clock()
        for task_id in [task_id for task_id, rec in self._records.items() if _expired(rec, now)]:
            del self._records[task_id]
        self._records[record.task.task_id] = record

    async def get(self, task_id: str) -> TaskRecord | None:
        record = self._records.get(task_id)
        if record is None:
            return None
        if _expired(record, self._clock()):
            del self._records[task_id]
            return None
        return record


def _expired(record: TaskRecord, now: datetime) -> bool:
    return record.expires_at is not None and now >= record.expires_at


class Tasks(Extension):
    """The Tasks extension: server-decided task-augmented `tools/call` plus `tasks/*`.

    Args:
        augment: Per-request augmentation predicate over the validated
            `tools/call` params. This is SEP-2663's "the server decides, at its
            discretion, per request": `None` (the default) augments every
            eligible call; a `False` return passes the call through untouched,
            exactly as for a non-declaring client.
        clock: Source of the current UTC time, used for the wire timestamps and
            TTL deadlines. Inject a fixed clock for deterministic tests.
        default_ttl_ms: Retention for recorded tasks, in milliseconds, stamped
            as `ttlMs` on the wire. `None` (the default) retains tasks for the
            store's lifetime.
        store: Task persistence. Defaults to a per-process `InMemoryTaskStore`
            sharing `clock`.

    Raises:
        ValueError: If `default_ttl_ms` is zero or negative.
    """

    identifier = EXTENSION_ID

    def __init__(
        self,
        *,
        augment: Callable[[CallToolRequestParams], bool] | None = None,
        clock: Clock = _utc_now,
        default_ttl_ms: int | None = None,
        store: TaskStore | None = None,
    ) -> None:
        if default_ttl_ms is not None and default_ttl_ms < 1:
            raise ValueError(f"default_ttl_ms must be a positive number of milliseconds, got {default_ttl_ms}")
        self._augment = augment
        self._clock = clock
        self._default_ttl_ms = default_ttl_ms
        self._store: TaskStore = store if store is not None else InMemoryTaskStore(clock=clock)

    def methods(self) -> Sequence[MethodBinding]:
        # Version-scoped to the modern wire: SEP-2663 is "not defined" under
        # 2025-11-25, so a legacy call must be METHOD_NOT_FOUND, not a capability
        # error the legacy client could never satisfy.
        modern = frozenset(MODERN_PROTOCOL_VERSIONS)
        return [
            MethodBinding("tasks/get", GetTaskRequestParams, self._handle_get, protocol_versions=modern),
            MethodBinding("tasks/update", UpdateTaskRequestParams, self._handle_update, protocol_versions=modern),
            MethodBinding("tasks/cancel", CancelTaskRequestParams, self._handle_cancel, protocol_versions=modern),
        ]

    async def intercept_tool_call(
        self,
        params: CallToolRequestParams,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        # SEP-2663: the server decides augmentation; the legacy `params.task` field
        # is ignored. Only augment for a client that declared the extension on the
        # request, and never alter a plain (non-declaring) client's call.
        if not _client_declared_tasks(ctx):
            return await call_next(ctx)
        if self._augment is not None and not self._augment(params):
            # The server declined this request, so the call -- errors included --
            # behaves exactly as for a non-declaring client.
            return await call_next(ctx)
        try:
            result = await call_next(ctx)
            if isinstance(result, ErrorData):
                # A nested extension returned the error instead of raising (the
                # runner's middleware error channel); fold it into the same arm.
                raise MCPError.from_error_data(result)
        except MCPError as exc:
            # SEP-2663: a JSON-RPC error during execution is a `failed` task,
            # with the error inlined on `tasks/get`. The declaring client gets
            # the failed `CreateTaskResult`, not the JSON-RPC error.
            error = exc.error.model_dump(by_alias=True, mode="json", exclude_none=True)
            return await self._create_task(status="failed", error=error, status_message=exc.error.message)
        payload = _wire_payload(result)
        if payload.get("resultType") == "input_required":
            # A multi round-trip interim: the logical call has not produced its
            # outcome yet, so it is not a task. The MRTR exchange resolves on the
            # original `tools/call` and the leg that completes becomes the task.
            return result
        # A tool result -- even `isError: true` -- is a completed task. Store a
        # copy: the chain's dict must not alias the durable record.
        return await self._create_task(status="completed", result=deepcopy(payload))

    async def _create_task(
        self,
        *,
        status: TaskStatus,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        status_message: str | None = None,
    ) -> CreateTaskResult:
        """Mint, durably record, and announce a born-terminal task."""
        now = self._clock()
        stamp = _wire_timestamp(now)
        task = Task(
            task_id=f"task_{secrets.token_urlsafe(16)}",  # bearer capability: >= 128 bits of entropy
            status=status,
            status_message=status_message,
            created_at=stamp,
            last_updated_at=stamp,
            ttl_ms=self._default_ttl_ms,
        )
        expires_at = now + timedelta(milliseconds=self._default_ttl_ms) if self._default_ttl_ms is not None else None
        await self._store.put(TaskRecord(task=task, result=result, error=error, expires_at=expires_at))
        return CreateTaskResult(
            task_id=task.task_id,
            status=task.status,
            status_message=task.status_message,
            created_at=task.created_at,
            last_updated_at=task.last_updated_at,
            ttl_ms=task.ttl_ms,
        )

    async def _handle_get(self, ctx: ServerRequestContext[Any, Any], params: GetTaskRequestParams) -> HandlerResult:
        require_client_extension(ctx, EXTENSION_ID)
        record = await self._require(params.task_id)
        detailed = record.task.model_dump(by_alias=True, exclude_none=True)
        detailed["resultType"] = "complete"
        # The outcome is inlined per status -- `result` for `completed` (even
        # `isError: true`), `error` for `failed`, never both. Serve copies so a
        # caller mutating the response cannot corrupt the stored record.
        if record.task.status == "completed":
            detailed["result"] = deepcopy(record.result)
        else:
            detailed["error"] = deepcopy(record.error)
        return detailed

    async def _handle_update(
        self, ctx: ServerRequestContext[Any, Any], params: UpdateTaskRequestParams
    ) -> HandlerResult:
        require_client_extension(ctx, EXTENSION_ID)
        await self._require(params.task_id)
        # No input requests are ever outstanding here (tasks are born terminal),
        # and SEP-2663 instructs servers to ignore `inputResponses` for unknown or
        # already-satisfied keys, so every well-addressed update acks as a no-op.
        return EmptyResult(result_type="complete")

    async def _handle_cancel(
        self, ctx: ServerRequestContext[Any, Any], params: CancelTaskRequestParams
    ) -> HandlerResult:
        require_client_extension(ctx, EXTENSION_ID)
        await self._require(params.task_id)
        # Cancellation is cooperative and may never take effect (SEP-2663 lets a
        # task reach a terminal status other than `cancelled` when the work
        # finished first). Here the tool has always finished before a `tasks/*`
        # request can arrive, so the task keeps its status and the ack is empty.
        return EmptyResult(result_type="complete")

    async def _require(self, task_id: str) -> TaskRecord:
        record = await self._store.get(task_id)
        if record is None:
            raise MCPError(code=INVALID_PARAMS, message=f"Unknown or expired task {task_id!r}")
        return record


def _wire_payload(result: HandlerResult) -> dict[str, Any]:
    """Normalize a `call_next` outcome to the wire dict the chain would emit.

    The stock composition hands the interceptor the already-serialized dict; an
    extension or middleware nested inside this one may short-circuit with a
    model (dumped the way the runner would) or `None` (an empty result).
    """
    if isinstance(result, BaseModel):
        return result.model_dump(by_alias=True, mode="json", exclude_none=True)
    return result if result is not None else {}


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
