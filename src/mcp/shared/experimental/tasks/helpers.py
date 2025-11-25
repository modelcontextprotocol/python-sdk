"""
Helper functions for task management.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from anyio.abc import TaskGroup

from mcp.shared.experimental.tasks.context import TaskContext
from mcp.shared.experimental.tasks.store import TaskStore
from mcp.types import CreateTaskResult, Result, Task, TaskMetadata, TaskStatus

if TYPE_CHECKING:
    from mcp.server.session import ServerSession


def is_terminal(status: TaskStatus) -> bool:
    """
    Check if a task status represents a terminal state.

    Terminal states are those where the task has finished and will not change.

    Args:
        status: The task status to check

    Returns:
        True if the status is terminal (completed, failed, or cancelled)
    """
    return status in ("completed", "failed", "cancelled")


def generate_task_id() -> str:
    """Generate a unique task ID."""
    return str(uuid4())


def create_task_state(
    metadata: TaskMetadata,
    task_id: str | None = None,
) -> Task:
    """
    Create a Task object with initial state.

    This is a helper for TaskStore implementations.

    Args:
        metadata: Task metadata
        task_id: Optional task ID (generated if not provided)

    Returns:
        A new Task in "working" status
    """
    now = datetime.now(timezone.utc)
    return Task(
        taskId=task_id or generate_task_id(),
        status="working",
        createdAt=now,
        lastUpdatedAt=now,
        ttl=metadata.ttl,
        pollInterval=500,  # Default 500ms poll interval
    )


@asynccontextmanager
async def task_execution(
    task_id: str,
    store: TaskStore,
    session: "ServerSession | None" = None,
) -> AsyncIterator[TaskContext]:
    """
    Context manager for safe task execution.

    Loads a task from the store and provides a TaskContext for the work.
    If an unhandled exception occurs, the task is automatically marked as failed
    and the exception is suppressed (since the failure is captured in task state).

    This is the recommended pattern for executing task work, especially in
    distributed scenarios where the worker may be a separate process.

    Args:
        task_id: The task identifier to execute
        store: The task store (must be accessible by the worker)
        session: Optional session for sending notifications (often None for workers)

    Yields:
        TaskContext for updating status and completing/failing the task

    Raises:
        ValueError: If the task is not found in the store

    Example (in-memory):
        async def work():
            async with task_execution(task.taskId, store) as ctx:
                await ctx.update_status("Processing...")
                result = await do_work()
                await ctx.complete(result)

        task_group.start_soon(work)

    Example (distributed worker):
        async def worker_process(task_id: str):
            store = RedisTaskStore(redis_url)
            async with task_execution(task_id, store) as ctx:
                await ctx.update_status("Working...")
                result = await do_work()
                await ctx.complete(result)
    """
    task = await store.get_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    ctx = TaskContext(task, store, session)
    try:
        yield ctx
    except Exception as e:
        # Auto-fail the task if an exception occurs and task isn't already terminal
        # Exception is suppressed since failure is captured in task state
        if not is_terminal(ctx.task.status):
            await ctx.fail(str(e), notify=session is not None)
        # Don't re-raise - the failure is recorded in task state


async def run_task(
    task_group: TaskGroup,
    store: TaskStore,
    metadata: TaskMetadata,
    work: Callable[[TaskContext], Awaitable[Result]],
    *,
    session: "ServerSession | None" = None,
    task_id: str | None = None,
) -> tuple[CreateTaskResult, TaskContext]:
    """
    Create a task and spawn work to execute it.

    This is a convenience helper for in-process task execution.
    For distributed systems, you'll want to handle task creation
    and execution separately.

    Args:
        task_group: The anyio TaskGroup to spawn work in
        store: The task store for state management
        metadata: Task metadata (ttl, etc.)
        work: Async function that does the actual work
        session: Optional session for sending notifications
        task_id: Optional task ID (generated if not provided)

    Returns:
        Tuple of (CreateTaskResult to return to client, TaskContext for cancellation)

    Example:
        async with anyio.create_task_group() as tg:
            @server.call_tool()
            async def handle_tool(name: str, args: dict):
                ctx = server.request_context
                if ctx.experimental.is_task:
                    result, task_ctx = await run_task(
                        tg,
                        store,
                        ctx.experimental.task_metadata,
                        lambda ctx: do_long_work(ctx, args),
                        session=ctx.session,
                    )
                    # Optionally store task_ctx for cancellation handling
                    return result
                else:
                    return await do_work_sync(args)
    """
    task = await store.create_task(metadata, task_id)
    ctx = TaskContext(task, store, session)

    async def execute() -> None:
        try:
            result = await work(ctx)
            # Only complete if not already in terminal state (e.g., cancelled)
            if not is_terminal(ctx.task.status):
                await ctx.complete(result)
        except Exception as e:
            # Only fail if not already in terminal state
            if not is_terminal(ctx.task.status):
                await ctx.fail(str(e))

    # Spawn the work in the task group
    task_group.start_soon(execute)

    return CreateTaskResult(task=task), ctx
