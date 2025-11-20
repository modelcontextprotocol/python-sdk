"""
Experimental client-side task support.

This module provides client methods for interacting with MCP tasks.

WARNING: These APIs are experimental and may change without notice.

Example:
    # Get task status
    status = await session.experimental.get_task(task_id)

    # Get task result when complete
    if status.status == "completed":
        result = await session.experimental.get_task_result(task_id, CallToolResult)

    # List all tasks
    tasks = await session.experimental.list_tasks()

    # Cancel a task
    await session.experimental.cancel_task(task_id)
"""

from typing import TYPE_CHECKING, TypeVar

import mcp.types as types

if TYPE_CHECKING:
    from mcp.client.session import ClientSession

ResultT = TypeVar("ResultT", bound=types.Result)


class ExperimentalClientFeatures:
    """
    Experimental client features for tasks and other experimental APIs.

    WARNING: These APIs are experimental and may change without notice.

    Access via session.experimental:
        status = await session.experimental.get_task(task_id)
    """

    def __init__(self, session: "ClientSession") -> None:
        self._session = session

    async def get_task(self, task_id: str) -> types.GetTaskResult:
        """
        Get the current status of a task.

        Args:
            task_id: The task identifier

        Returns:
            GetTaskResult containing the task status and metadata
        """
        return await self._session.send_request(
            types.ClientRequest(
                types.GetTaskRequest(
                    params=types.GetTaskRequestParams(taskId=task_id),
                )
            ),
            types.GetTaskResult,
        )

    async def get_task_result(
        self,
        task_id: str,
        result_type: type[ResultT],
    ) -> ResultT:
        """
        Get the result of a completed task.

        The result type depends on the original request type:
        - tools/call tasks return CallToolResult
        - Other request types return their corresponding result type

        Args:
            task_id: The task identifier
            result_type: The expected result type (e.g., CallToolResult)

        Returns:
            The task result, validated against result_type
        """
        return await self._session.send_request(
            types.ClientRequest(
                types.GetTaskPayloadRequest(
                    params=types.GetTaskPayloadRequestParams(taskId=task_id),
                )
            ),
            result_type,
        )

    async def list_tasks(
        self,
        cursor: str | None = None,
    ) -> types.ListTasksResult:
        """
        List all tasks.

        Args:
            cursor: Optional pagination cursor

        Returns:
            ListTasksResult containing tasks and optional next cursor
        """
        params = types.PaginatedRequestParams(cursor=cursor) if cursor else None
        return await self._session.send_request(
            types.ClientRequest(
                types.ListTasksRequest(params=params),
            ),
            types.ListTasksResult,
        )

    async def cancel_task(self, task_id: str) -> types.CancelTaskResult:
        """
        Cancel a running task.

        Args:
            task_id: The task identifier

        Returns:
            CancelTaskResult with the updated task state
        """
        return await self._session.send_request(
            types.ClientRequest(
                types.CancelTaskRequest(
                    params=types.CancelTaskRequestParams(taskId=task_id),
                )
            ),
            types.CancelTaskResult,
        )
