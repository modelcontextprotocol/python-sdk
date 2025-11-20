"""
TaskContext - Context for task work to interact with state and notifications.
"""

from typing import TYPE_CHECKING

from mcp.shared.experimental.tasks.store import TaskStore
from mcp.types import (
    Result,
    ServerNotification,
    Task,
    TaskStatusNotification,
    TaskStatusNotificationParams,
)

if TYPE_CHECKING:
    from mcp.server.session import ServerSession


class TaskContext:
    """
    Context provided to task work for state management and notifications.

    This wraps a TaskStore and optional session, providing a clean API
    for task work to update status, complete, fail, and send notifications.

    Example:
        async def my_task_work(ctx: TaskContext) -> CallToolResult:
            await ctx.update_status("Starting processing...")

            for i, item in enumerate(items):
                await ctx.update_status(f"Processing item {i+1}/{len(items)}")
                if ctx.is_cancelled:
                    return CallToolResult(content=[TextContent(type="text", text="Cancelled")])
                process(item)

            return CallToolResult(content=[TextContent(type="text", text="Done!")])
    """

    def __init__(
        self,
        task: Task,
        store: TaskStore,
        session: "ServerSession | None" = None,
    ):
        self._task = task
        self._store = store
        self._session = session
        self._cancelled = False

    @property
    def task_id(self) -> str:
        """The task identifier."""
        return self._task.taskId

    @property
    def task(self) -> Task:
        """The current task state."""
        return self._task

    @property
    def is_cancelled(self) -> bool:
        """Whether cancellation has been requested."""
        return self._cancelled

    def request_cancellation(self) -> None:
        """
        Request cancellation of this task.

        This sets is_cancelled=True. Task work should check this
        periodically and exit gracefully if set.
        """
        self._cancelled = True

    async def update_status(self, message: str, *, notify: bool = True) -> None:
        """
        Update the task's status message.

        Args:
            message: The new status message
            notify: Whether to send a notification to the client
        """
        self._task = await self._store.update_task(
            self.task_id,
            status_message=message,
        )
        if notify:
            await self._send_notification()

    async def complete(self, result: Result, *, notify: bool = True) -> None:
        """
        Mark the task as completed with the given result.

        Args:
            result: The task result
            notify: Whether to send a notification to the client
        """
        await self._store.store_result(self.task_id, result)
        self._task = await self._store.update_task(
            self.task_id,
            status="completed",
        )
        if notify:
            await self._send_notification()

    async def fail(self, error: str, *, notify: bool = True) -> None:
        """
        Mark the task as failed with an error message.

        Args:
            error: The error message
            notify: Whether to send a notification to the client
        """
        self._task = await self._store.update_task(
            self.task_id,
            status="failed",
            status_message=error,
        )
        if notify:
            await self._send_notification()

    async def _send_notification(self) -> None:
        """Send a task status notification to the client."""
        if self._session is None:
            return

        await self._session.send_notification(
            ServerNotification(
                TaskStatusNotification(
                    params=TaskStatusNotificationParams(
                        taskId=self._task.taskId,
                        status=self._task.status,
                        statusMessage=self._task.statusMessage,
                        createdAt=self._task.createdAt,
                        ttl=self._task.ttl,
                        pollInterval=self._task.pollInterval,
                    )
                )
            )
        )
