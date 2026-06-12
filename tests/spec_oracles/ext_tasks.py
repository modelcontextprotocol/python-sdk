# GENERATED FILE — DO NOT EDIT.
# Source: https://github.com/modelcontextprotocol/experimental-ext-tasks/blob/dd47977f4e4069aa4147d816f52ebb9a27c11315/schema/draft/schema.json
# Protocol version: n/a   Generator: datamodel-code-generator 0.57.0
# Regenerate: uv run --frozen python scripts/update_spec_types.py tasks [--sha <new-sha>]
# pyright: reportIncompatibleVariableOverride=false
from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import ConfigDict, Field

from tests.spec_oracles._base import OracleModel

McpTasksExtension: TypeAlias = Any


Id: TypeAlias = int


class Params(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]


class CancelTaskRequest(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    jsonrpc: Literal["2.0"]
    id: str | Id
    method: Literal["tasks/cancel"]
    params: Params


ProgressToken: TypeAlias = int


class IoModelcontextprotocolRelatedTask(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]


class Meta(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    progress_token: Annotated[str | ProgressToken | None, Field(alias="progressToken")] = None
    io_modelcontextprotocol_related_task: Annotated[
        IoModelcontextprotocolRelatedTask | None,
        Field(alias="io.modelcontextprotocol/related-task"),
    ] = None


class CancelTaskResult(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[Meta | None, Field(alias="_meta")] = None


class CancelledTask(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["cancelled"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None


class CompletedTask(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["completed"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None
    result: dict[str, Any]


class Meta1(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    progress_token: Annotated[str | ProgressToken | None, Field(alias="progressToken")] = None
    io_modelcontextprotocol_related_task: Annotated[
        IoModelcontextprotocolRelatedTask | None,
        Field(alias="io.modelcontextprotocol/related-task"),
    ] = None


class CreateTaskResult(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[Meta1 | None, Field(alias="_meta")] = None
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["working", "input_required", "completed", "failed", "cancelled"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None


class DetailedTask1(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["working"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None


class DetailedTask2(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["input_required"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None
    input_requests: Annotated[dict[str, Any], Field(alias="inputRequests")]


class DetailedTask3(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["completed"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None
    result: dict[str, Any]


class DetailedTask4(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["failed"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None
    error: dict[str, Any]


class DetailedTask5(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["cancelled"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None


DetailedTask: TypeAlias = DetailedTask1 | DetailedTask2 | DetailedTask3 | DetailedTask4 | DetailedTask5


class FailedTask(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["failed"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None
    error: dict[str, Any]


class GetTaskRequest(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    jsonrpc: Literal["2.0"]
    id: str | Id
    method: Literal["tasks/get"]
    params: Params


class Meta2(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    progress_token: Annotated[str | ProgressToken | None, Field(alias="progressToken")] = None
    io_modelcontextprotocol_related_task: Annotated[
        IoModelcontextprotocolRelatedTask | None,
        Field(alias="io.modelcontextprotocol/related-task"),
    ] = None


class GetTaskResult1(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["working"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None


class GetTaskResult2(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["input_required"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None
    input_requests: Annotated[dict[str, Any], Field(alias="inputRequests")]


class GetTaskResult3(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["completed"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None
    result: dict[str, Any]


class GetTaskResult4(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["failed"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None
    error: dict[str, Any]


class GetTaskResult5(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["cancelled"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None


class GetTaskResult6(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[Meta2 | None, Field(alias="_meta")] = None


class GetTaskResult7(GetTaskResult1, GetTaskResult6):
    model_config = ConfigDict(
        extra="allow",
    )


class GetTaskResult8(GetTaskResult2, GetTaskResult6):
    model_config = ConfigDict(
        extra="allow",
    )


class GetTaskResult9(GetTaskResult3, GetTaskResult6):
    model_config = ConfigDict(
        extra="allow",
    )


class GetTaskResult10(GetTaskResult4, GetTaskResult6):
    model_config = ConfigDict(
        extra="allow",
    )


class GetTaskResult11(GetTaskResult5, GetTaskResult6):
    model_config = ConfigDict(
        extra="allow",
    )


GetTaskResult: TypeAlias = GetTaskResult7 | GetTaskResult8 | GetTaskResult9 | GetTaskResult10 | GetTaskResult11


InputRequest: TypeAlias = Any


InputRequests: TypeAlias = dict[str, Any]


class InputRequiredTask(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["input_required"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None
    input_requests: Annotated[dict[str, Any], Field(alias="inputRequests")]


InputResponse: TypeAlias = Any


InputResponses: TypeAlias = dict[str, Any]


class Task(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["working", "input_required", "completed", "failed", "cancelled"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None


class TaskStatusNotificationParams1(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["working"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None


class TaskStatusNotificationParams2(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["input_required"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None
    input_requests: Annotated[dict[str, Any], Field(alias="inputRequests")]


class TaskStatusNotificationParams3(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["completed"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None
    result: dict[str, Any]


class TaskStatusNotificationParams4(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["failed"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None
    error: dict[str, Any]


class TaskStatusNotificationParams5(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["cancelled"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None


class TaskStatusNotificationParams6(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None


class TaskStatusNotificationParams7(TaskStatusNotificationParams1, TaskStatusNotificationParams6):
    model_config = ConfigDict(
        extra="allow",
    )


class TaskStatusNotificationParams8(TaskStatusNotificationParams2, TaskStatusNotificationParams6):
    model_config = ConfigDict(
        extra="allow",
    )


class TaskStatusNotificationParams9(TaskStatusNotificationParams3, TaskStatusNotificationParams6):
    model_config = ConfigDict(
        extra="allow",
    )


class TaskStatusNotificationParams10(TaskStatusNotificationParams4, TaskStatusNotificationParams6):
    model_config = ConfigDict(
        extra="allow",
    )


class TaskStatusNotificationParams11(TaskStatusNotificationParams5, TaskStatusNotificationParams6):
    model_config = ConfigDict(
        extra="allow",
    )


TaskStatusNotificationParams: TypeAlias = (
    TaskStatusNotificationParams7
    | TaskStatusNotificationParams8
    | TaskStatusNotificationParams9
    | TaskStatusNotificationParams10
    | TaskStatusNotificationParams11
)


class Params21(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["working"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None


class Params22(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["input_required"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None
    input_requests: Annotated[dict[str, Any], Field(alias="inputRequests")]


class Params23(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["completed"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None
    result: dict[str, Any]


class Params24(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["failed"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None
    error: dict[str, Any]


class Params25(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["cancelled"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None


class Params26(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[dict[str, Any] | None, Field(alias="_meta")] = None


class Params27(Params21, Params26):
    model_config = ConfigDict(
        extra="allow",
    )


class Params28(Params22, Params26):
    model_config = ConfigDict(
        extra="allow",
    )


class Params29(Params23, Params26):
    model_config = ConfigDict(
        extra="allow",
    )


class Params210(Params24, Params26):
    model_config = ConfigDict(
        extra="allow",
    )


class Params211(Params25, Params26):
    model_config = ConfigDict(
        extra="allow",
    )


Params2: TypeAlias = Params27 | Params28 | Params29 | Params210 | Params211


class TaskStatusNotification(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    jsonrpc: Literal["2.0"]
    method: Literal["notifications/tasks"]
    params: Params2


TaskStatus: TypeAlias = Literal["working", "input_required", "completed", "failed", "cancelled"]


class TaskSubscriptionAcknowledgedNotifications(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_ids: Annotated[list[str] | None, Field(alias="taskIds")] = None


class TaskSubscriptionNotifications(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_ids: Annotated[list[str] | None, Field(alias="taskIds")] = None


TasksExtensionCapability: TypeAlias = dict[str, Any]


class Params3(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    input_responses: Annotated[dict[str, Any], Field(alias="inputResponses")]


class UpdateTaskRequest(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    jsonrpc: Literal["2.0"]
    id: str | Id
    method: Literal["tasks/update"]
    params: Params3


class Meta3(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    progress_token: Annotated[str | ProgressToken | None, Field(alias="progressToken")] = None
    io_modelcontextprotocol_related_task: Annotated[
        IoModelcontextprotocolRelatedTask | None,
        Field(alias="io.modelcontextprotocol/related-task"),
    ] = None


class UpdateTaskResult(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    meta: Annotated[Meta3 | None, Field(alias="_meta")] = None


class WorkingTask(OracleModel):
    model_config = ConfigDict(
        extra="allow",
    )
    task_id: Annotated[str, Field(alias="taskId")]
    status: Literal["working"]
    status_message: Annotated[str | None, Field(alias="statusMessage")] = None
    created_at: Annotated[str, Field(alias="createdAt")]
    last_updated_at: Annotated[str, Field(alias="lastUpdatedAt")]
    ttl_ms: Annotated[float | None, Field(alias="ttlMs")]
    poll_interval_ms: Annotated[float | None, Field(alias="pollIntervalMs")] = None


SPEC_DEFS: tuple[str, ...] = (
    "CancelTaskRequest",
    "CancelTaskResult",
    "CancelledTask",
    "CompletedTask",
    "CreateTaskResult",
    "DetailedTask",
    "FailedTask",
    "GetTaskRequest",
    "GetTaskResult",
    "InputRequest",
    "InputRequests",
    "InputRequiredTask",
    "InputResponse",
    "InputResponses",
    "Task",
    "TaskStatus",
    "TaskStatusNotification",
    "TaskStatusNotificationParams",
    "TaskSubscriptionAcknowledgedNotifications",
    "TaskSubscriptionNotifications",
    "TasksExtensionCapability",
    "UpdateTaskRequest",
    "UpdateTaskResult",
    "WorkingTask",
)
