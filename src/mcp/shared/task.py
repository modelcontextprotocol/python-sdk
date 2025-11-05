"""Task storage interface and utilities for MCP task-based execution."""

from abc import ABC, abstractmethod
from typing import Any, Literal

from mcp.types import Request, RequestId, Result, Task, TaskMetadata

TaskStatus = Literal["submitted", "working", "input_required", "completed", "failed", "cancelled", "unknown"]


class TaskStore(ABC):
    """
    Interface for storing and retrieving task state and results.

    Similar to Transport, this allows pluggable task storage implementations
    (in-memory, database, distributed cache, etc.).
    """

    @abstractmethod
    async def create_task(self, task: TaskMetadata, request_id: RequestId, request: Request[Any, Any]) -> None:
        """
        Create a new task with the given metadata and original request.

        Args:
            task: The task creation metadata from the request
            request_id: The JSON-RPC request ID
            request: The original request that triggered task creation
        """
        ...

    @abstractmethod
    async def get_task(self, task_id: str) -> Task | None:
        """
        Get the current status of a task.

        Args:
            task_id: The task identifier

        Returns:
            The task state including status, keepAlive, pollFrequency, and optional error,
            or None if task not found
        """
        ...

    @abstractmethod
    async def store_task_result(self, task_id: str, result: Result) -> None:
        """
        Store the result of a completed task.

        Args:
            task_id: The task identifier
            result: The result to store
        """
        ...

    @abstractmethod
    async def get_task_result(self, task_id: str) -> Result:
        """
        Retrieve the stored result of a task.

        Args:
            task_id: The task identifier

        Returns:
            The stored result

        Raises:
            Exception: If task not found or has no result
        """
        ...

    @abstractmethod
    async def update_task_status(self, task_id: str, status: TaskStatus, error: str | None = None) -> None:
        """
        Update a task's status (e.g., to 'cancelled', 'failed', 'completed').

        Args:
            task_id: The task identifier
            status: The new status
            error: Optional error message if status is 'failed' or 'cancelled'
        """
        ...

    @abstractmethod
    async def list_tasks(self, cursor: str | None = None) -> dict[str, list[Task] | str | None]:
        """
        List tasks, optionally starting from a pagination cursor.

        Args:
            cursor: Optional cursor for pagination

        Returns:
            A dictionary containing:
            - 'tasks': list of Task objects
            - 'nextCursor': optional string for next page (None if no more pages)

        Raises:
            Exception: If cursor is invalid
        """
        ...

    @abstractmethod
    async def delete_task(self, task_id: str) -> None:
        """
        Delete a task from storage.

        Args:
            task_id: The task identifier

        Raises:
            Exception: If task not found
        """
        ...


def is_terminal(status: TaskStatus) -> bool:
    """
    Check if a task status represents a terminal state.

    Terminal states are those where the task has finished and will not change.

    Args:
        status: The task status to check

    Returns:
        True if the status is terminal (completed, failed, cancelled, or unknown)
    """
    return status in ("completed", "failed", "cancelled", "unknown")
