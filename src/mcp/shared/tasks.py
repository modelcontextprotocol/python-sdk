"""Wire models for the Tasks extension (`io.modelcontextprotocol/tasks`, SEP-2663).

SEP-2663 (https://modelcontextprotocol.io/seps/2663-tasks-extension.md) is an
opt-in extension, wire-incompatible with the 2025-11-25 in-core Tasks design that
still ships (types-only) in `mcp_types`. This module therefore defines its own
SEP-2663-shaped models rather than reusing `mcp_types.{Task, CreateTaskResult, ...}`.

Both sides of the wire share these shapes: the server runtime (`mcp.server.tasks`)
serves them, and client code sends the typed `tasks/*` request wrappers and parses
`tasks/get` responses with `GetTaskResult`. The module depends only on `mcp_types`
and pydantic.
"""

from __future__ import annotations

from typing import Any, Literal

from mcp_types import Request, RequestParams, Result
from pydantic import (
    BaseModel,
    ConfigDict,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    model_serializer,
)
from pydantic.alias_generators import to_camel

__all__ = [
    "EXTENSION_ID",
    "CancelTaskRequest",
    "CancelTaskRequestParams",
    "CreateTaskResult",
    "GetTaskRequest",
    "GetTaskRequestParams",
    "GetTaskResult",
    "Task",
    "TaskStatus",
    "UpdateTaskRequest",
    "UpdateTaskRequestParams",
]

EXTENSION_ID = "io.modelcontextprotocol/tasks"
"""The Tasks extension identifier (SEP-2663)."""

TaskStatus = Literal["working", "input_required", "completed", "failed", "cancelled"]
"""SEP-2663 task statuses."""


class _CarriesTtlMs(BaseModel):
    """Keeps `ttlMs` on the wire even when null.

    `ttlMs` is required-but-nullable in the extension schema (`ttlMs: number |
    null`; null means unlimited), but the SDK serializes results with
    `exclude_none`, which would drop the key. This wrap serializer reinstates it
    after the exclusions run, leaving the genuinely optional fields
    (`statusMessage`, `pollIntervalMs`) excludable.
    """

    ttl_ms: int | None = None

    @model_serializer(mode="wrap")
    def _keep_ttl_ms(self, handler: SerializerFunctionWrapHandler, info: SerializationInfo) -> dict[str, Any]:
        data = handler(self)
        data.setdefault("ttlMs" if info.by_alias else "ttl_ms", self.ttl_ms)
        return data


class _TasksModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Task(_CarriesTtlMs, _TasksModel):
    """SEP-2663 task snapshot (note the `*Ms` field names, unlike the 2025 design)."""

    task_id: str
    status: TaskStatus
    status_message: str | None = None
    created_at: str
    last_updated_at: str
    ttl_ms: int | None = None
    poll_interval_ms: int | None = None


class CreateTaskResult(_CarriesTtlMs, Result):
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


class GetTaskRequestParams(RequestParams):
    task_id: str


class CancelTaskRequestParams(RequestParams):
    task_id: str


class UpdateTaskRequestParams(RequestParams):
    task_id: str
    input_responses: dict[str, Any]


class GetTaskRequest(Request[GetTaskRequestParams, Literal["tasks/get"]]):
    """SEP-2663 `tasks/get` request, typed for client-side `send_request`."""

    method: Literal["tasks/get"] = "tasks/get"
    params: GetTaskRequestParams


class CancelTaskRequest(Request[CancelTaskRequestParams, Literal["tasks/cancel"]]):
    """SEP-2663 `tasks/cancel` request, typed for client-side `send_request`."""

    method: Literal["tasks/cancel"] = "tasks/cancel"
    params: CancelTaskRequestParams


class UpdateTaskRequest(Request[UpdateTaskRequestParams, Literal["tasks/update"]]):
    """SEP-2663 `tasks/update` request, typed for client-side `send_request`."""

    method: Literal["tasks/update"] = "tasks/update"
    params: UpdateTaskRequestParams


class GetTaskResult(Task):
    """SEP-2663 `tasks/get` response: the task snapshot with its outcome inlined.

    A lenient client-side parse model: `result` is set when the task `completed`
    (even a tool result with `isError: true`), `error` (the JSON-RPC error dict)
    when it `failed`, and both stay `None` for non-terminal statuses.
    """

    result_type: str = "complete"
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
