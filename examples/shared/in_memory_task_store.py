"""
In-memory implementation of TaskStore for demonstration purposes.

This implementation stores all tasks in memory and provides automatic cleanup
based on the keepAlive duration specified in the task metadata.

Note: This is not suitable for production use as all data is lost on restart.
For production, consider implementing TaskStore with a database or distributed cache.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

from mcp.shared.task import TaskStatus, TaskStore, is_terminal
from mcp.types import Request, RequestId, Result, Task, TaskMetadata


@dataclass
class StoredTask:
    """Internal storage representation of a task."""

    task: Task
    request: Request[Any, Any]
    request_id: RequestId
    result: Result | None = None


class InMemoryTaskStore(TaskStore):
    """
    A simple in-memory implementation of TaskStore for demonstration purposes.

    This implementation stores all tasks in memory and provides automatic cleanup
    based on the keepAlive duration specified in the task metadata.

    Note: This is not suitable for production use as all data is lost on restart.
    For production, consider implementing TaskStore with a database or distributed cache.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, StoredTask] = {}
        self._cleanup_tasks: dict[str, asyncio.Task[None]] = {}

    async def create_task(
        self, task: TaskMetadata, request_id: RequestId, request: Request[Any, Any], session_id: str | None = None
    ) -> None:
        """Create a new task with the given metadata and original request."""
        task_id = task.taskId

        if task_id in self._tasks:
            raise ValueError(f"Task with ID {task_id} already exists")

        task_obj = Task(
            taskId=task_id,
            status="submitted",
            keepAlive=task.keepAlive,
            pollInterval=500,  # Default 500ms poll frequency
        )

        self._tasks[task_id] = StoredTask(task=task_obj, request=request, request_id=request_id)

        # Schedule cleanup if keepAlive is specified
        if task.keepAlive is not None:
            self._schedule_cleanup(task_id, task.keepAlive / 1000.0)

    async def get_task(self, task_id: str, session_id: str | None = None) -> Task | None:
        """Get the current status of a task."""
        stored = self._tasks.get(task_id)
        if stored is None:
            return None

        # Return a copy to prevent external modification
        return Task(**stored.task.model_dump())

    async def store_task_result(self, task_id: str, result: Result, session_id: str | None = None) -> None:
        """Store the result of a completed task."""
        stored = self._tasks.get(task_id)
        if stored is None:
            raise ValueError(f"Task with ID {task_id} not found")

        stored.result = result
        stored.task.status = "completed"

        # Reset cleanup timer to start from now (if keepAlive is set)
        if stored.task.keepAlive is not None:
            self._cancel_cleanup(task_id)
            self._schedule_cleanup(task_id, stored.task.keepAlive / 1000.0)

    async def get_task_result(self, task_id: str, session_id: str | None = None) -> Result:
        """Retrieve the stored result of a task."""
        stored = self._tasks.get(task_id)
        if stored is None:
            raise ValueError(f"Task with ID {task_id} not found")

        if stored.result is None:
            raise ValueError(f"Task {task_id} has no result stored")

        return stored.result

    async def update_task_status(
        self, task_id: str, status: TaskStatus, error: str | None = None, session_id: str | None = None
    ) -> None:
        """Update a task's status."""
        stored = self._tasks.get(task_id)
        if stored is None:
            raise ValueError(f"Task with ID {task_id} not found")

        stored.task.status = status
        if error is not None:
            stored.task.error = error

        # If task is in a terminal state and has keepAlive, start cleanup timer
        if is_terminal(status) and stored.task.keepAlive is not None:
            self._cancel_cleanup(task_id)
            self._schedule_cleanup(task_id, stored.task.keepAlive / 1000.0)

    async def list_tasks(self, cursor: str | None = None, session_id: str | None = None) -> dict[str, Any]:
        """
        List tasks, optionally starting from a pagination cursor.

        Returns a dict with 'tasks' list and optional 'nextCursor' string.
        """
        PAGE_SIZE = 10
        all_task_ids = list(self._tasks.keys())

        start_index = 0
        if cursor is not None:
            try:
                cursor_index = all_task_ids.index(cursor)
                start_index = cursor_index + 1
            except ValueError:
                raise ValueError(f"Invalid cursor: {cursor}")

        page_task_ids = all_task_ids[start_index : start_index + PAGE_SIZE]
        tasks = [Task(**self._tasks[tid].task.model_dump()) for tid in page_task_ids]

        next_cursor = page_task_ids[-1] if start_index + PAGE_SIZE < len(all_task_ids) and page_task_ids else None

        return {"tasks": tasks, "nextCursor": next_cursor}

    async def delete_task(self, task_id: str, session_id: str | None = None) -> None:
        """Delete a task from storage."""
        if task_id not in self._tasks:
            raise ValueError(f"Task with ID {task_id} not found")

        # Cancel any scheduled cleanup
        self._cancel_cleanup(task_id)

        # Remove the task
        self._tasks.pop(task_id)

    def _schedule_cleanup(self, task_id: str, delay_seconds: float) -> None:
        """Schedule automatic cleanup of a task after the specified delay."""

        async def cleanup() -> None:
            await asyncio.sleep(delay_seconds)
            self._tasks.pop(task_id, None)
            self._cleanup_tasks.pop(task_id, None)

        task = asyncio.create_task(cleanup())
        self._cleanup_tasks[task_id] = task

    def _cancel_cleanup(self, task_id: str) -> None:
        """Cancel any scheduled cleanup for a task."""
        cleanup_task = self._cleanup_tasks.pop(task_id, None)
        if cleanup_task is not None and not cleanup_task.done():
            cleanup_task.cancel()

    def cleanup(self) -> None:
        """Cleanup all timers and tasks (useful for testing or graceful shutdown)."""
        for task in self._cleanup_tasks.values():
            if not task.done():
                task.cancel()
        self._cleanup_tasks.clear()
        self._tasks.clear()

    def get_all_tasks(self) -> list[Task]:
        """Get all tasks (useful for debugging). Returns copies to prevent modification."""
        return [Task(**stored.task.model_dump()) for stored in self._tasks.values()]
