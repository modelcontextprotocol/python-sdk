"""
Experimental task handler protocols for server -> client requests.

This module provides Protocol types and default handlers for when servers
send task-related requests to clients (the reverse of normal client -> server flow).

WARNING: These APIs are experimental and may change without notice.

Use cases:
- Server sends task-augmented sampling/elicitation request to client
- Client creates a local task, spawns background work, returns CreateTaskResult
- Server polls client's task status via tasks/get, tasks/result, etc.
"""

from typing import TYPE_CHECKING, Any, Protocol

import mcp.types as types
from mcp.shared.context import RequestContext

if TYPE_CHECKING:
    from mcp.client.session import ClientSession


class GetTaskHandlerFnT(Protocol):
    """Handler for tasks/get requests from server.

    WARNING: This is experimental and may change without notice.
    """

    async def __call__(
        self,
        context: RequestContext["ClientSession", Any],
        params: types.GetTaskRequestParams,
    ) -> types.GetTaskResult | types.ErrorData: ...  # pragma: no branch


class GetTaskResultHandlerFnT(Protocol):
    """Handler for tasks/result requests from server.

    WARNING: This is experimental and may change without notice.
    """

    async def __call__(
        self,
        context: RequestContext["ClientSession", Any],
        params: types.GetTaskPayloadRequestParams,
    ) -> types.GetTaskPayloadResult | types.ErrorData: ...  # pragma: no branch


class ListTasksHandlerFnT(Protocol):
    """Handler for tasks/list requests from server.

    WARNING: This is experimental and may change without notice.
    """

    async def __call__(
        self,
        context: RequestContext["ClientSession", Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListTasksResult | types.ErrorData: ...  # pragma: no branch


class CancelTaskHandlerFnT(Protocol):
    """Handler for tasks/cancel requests from server.

    WARNING: This is experimental and may change without notice.
    """

    async def __call__(
        self,
        context: RequestContext["ClientSession", Any],
        params: types.CancelTaskRequestParams,
    ) -> types.CancelTaskResult | types.ErrorData: ...  # pragma: no branch


class TaskAugmentedSamplingFnT(Protocol):
    """Handler for task-augmented sampling/createMessage requests from server.

    When server sends a CreateMessageRequest with task field, this callback
    is invoked. The callback should create a task, spawn background work,
    and return CreateTaskResult immediately.

    WARNING: This is experimental and may change without notice.
    """

    async def __call__(
        self,
        context: RequestContext["ClientSession", Any],
        params: types.CreateMessageRequestParams,
        task_metadata: types.TaskMetadata,
    ) -> types.CreateTaskResult | types.ErrorData: ...  # pragma: no branch


class TaskAugmentedElicitationFnT(Protocol):
    """Handler for task-augmented elicitation/create requests from server.

    When server sends an ElicitRequest with task field, this callback
    is invoked. The callback should create a task, spawn background work,
    and return CreateTaskResult immediately.

    WARNING: This is experimental and may change without notice.
    """

    async def __call__(
        self,
        context: RequestContext["ClientSession", Any],
        params: types.ElicitRequestParams,
        task_metadata: types.TaskMetadata,
    ) -> types.CreateTaskResult | types.ErrorData: ...  # pragma: no branch


# Default handlers for experimental task requests (return "not supported" errors)
async def default_get_task_handler(
    context: RequestContext["ClientSession", Any],
    params: types.GetTaskRequestParams,
) -> types.GetTaskResult | types.ErrorData:
    return types.ErrorData(
        code=types.METHOD_NOT_FOUND,
        message="tasks/get not supported",
    )


async def default_get_task_result_handler(
    context: RequestContext["ClientSession", Any],
    params: types.GetTaskPayloadRequestParams,
) -> types.GetTaskPayloadResult | types.ErrorData:
    return types.ErrorData(
        code=types.METHOD_NOT_FOUND,
        message="tasks/result not supported",
    )


async def default_list_tasks_handler(
    context: RequestContext["ClientSession", Any],
    params: types.PaginatedRequestParams | None,
) -> types.ListTasksResult | types.ErrorData:
    return types.ErrorData(
        code=types.METHOD_NOT_FOUND,
        message="tasks/list not supported",
    )


async def default_cancel_task_handler(
    context: RequestContext["ClientSession", Any],
    params: types.CancelTaskRequestParams,
) -> types.CancelTaskResult | types.ErrorData:
    return types.ErrorData(
        code=types.METHOD_NOT_FOUND,
        message="tasks/cancel not supported",
    )


async def default_task_augmented_sampling_callback(
    context: RequestContext["ClientSession", Any],
    params: types.CreateMessageRequestParams,
    task_metadata: types.TaskMetadata,
) -> types.CreateTaskResult | types.ErrorData:
    return types.ErrorData(
        code=types.INVALID_REQUEST,
        message="Task-augmented sampling not supported",
    )


async def default_task_augmented_elicitation_callback(
    context: RequestContext["ClientSession", Any],
    params: types.ElicitRequestParams,
    task_metadata: types.TaskMetadata,
) -> types.CreateTaskResult | types.ErrorData:
    return types.ErrorData(
        code=types.INVALID_REQUEST,
        message="Task-augmented elicitation not supported",
    )


def build_client_tasks_capability(
    *,
    list_tasks_handler: ListTasksHandlerFnT | None = None,
    cancel_task_handler: CancelTaskHandlerFnT | None = None,
    task_augmented_sampling_callback: TaskAugmentedSamplingFnT | None = None,
    task_augmented_elicitation_callback: TaskAugmentedElicitationFnT | None = None,
) -> types.ClientTasksCapability | None:
    """Build ClientTasksCapability from the provided handlers.

    This helper builds the appropriate capability object based on which
    handlers are provided (non-None and not the default handlers).

    WARNING: This is experimental and may change without notice.

    Args:
        list_tasks_handler: Handler for tasks/list requests
        cancel_task_handler: Handler for tasks/cancel requests
        task_augmented_sampling_callback: Handler for task-augmented sampling
        task_augmented_elicitation_callback: Handler for task-augmented elicitation

    Returns:
        ClientTasksCapability if any handlers are provided, None otherwise
    """
    has_list = list_tasks_handler is not None and list_tasks_handler is not default_list_tasks_handler
    has_cancel = cancel_task_handler is not None and cancel_task_handler is not default_cancel_task_handler
    has_sampling = (
        task_augmented_sampling_callback is not None
        and task_augmented_sampling_callback is not default_task_augmented_sampling_callback
    )
    has_elicitation = (
        task_augmented_elicitation_callback is not None
        and task_augmented_elicitation_callback is not default_task_augmented_elicitation_callback
    )

    # If no handlers are provided, return None
    if not any([has_list, has_cancel, has_sampling, has_elicitation]):
        return None

    # Build requests capability if any request handlers are provided
    requests_capability: types.ClientTasksRequestsCapability | None = None
    if has_sampling or has_elicitation:
        requests_capability = types.ClientTasksRequestsCapability(
            sampling=types.TasksSamplingCapability(createMessage=types.TasksCreateMessageCapability())
            if has_sampling
            else None,
            elicitation=types.TasksElicitationCapability(create=types.TasksCreateElicitationCapability())
            if has_elicitation
            else None,
        )

    return types.ClientTasksCapability(
        list=types.TasksListCapability() if has_list else None,
        cancel=types.TasksCancelCapability() if has_cancel else None,
        requests=requests_capability,
    )
