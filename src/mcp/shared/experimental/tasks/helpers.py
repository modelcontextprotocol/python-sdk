"""
Helper functions for task management.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from anyio.abc import TaskGroup

from mcp.shared.exceptions import McpError
from mcp.shared.experimental.tasks.context import TaskContext
from mcp.shared.experimental.tasks.store import TaskStore
from mcp.types import (
    INVALID_PARAMS,
    CancelTaskResult,
    CreateTaskResult,
    ErrorData,
    Result,
    Task,
    TaskMetadata,
    TaskStatus,
)

if TYPE_CHECKING:
    from mcp.server.session import ServerSession

# Metadata key for model-immediate-response (per MCP spec)
# Servers MAY include this in CreateTaskResult._meta to provide an immediate
# response string while the task executes in the background.
MODEL_IMMEDIATE_RESPONSE_KEY = "io.modelcontextprotocol/model-immediate-response"


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


async def cancel_task(
    store: TaskStore,
    task_id: str,
) -> CancelTaskResult:
    """
    Cancel a task with spec-compliant validation.

    Per spec: "Receivers MUST reject cancellation of terminal status tasks
    with -32602 (Invalid params)"

    This helper validates that the task exists and is not in a terminal state
    before setting it to "cancelled".

    Args:
        store: The task store
        task_id: The task identifier to cancel

    Returns:
        CancelTaskResult with the cancelled task state

    Raises:
        McpError: With INVALID_PARAMS (-32602) if:
            - Task does not exist
            - Task is already in a terminal state (completed, failed, cancelled)

    Example:
        @server.experimental.cancel_task()
        async def handle_cancel(request: CancelTaskRequest) -> CancelTaskResult:
            return await cancel_task(store, request.params.taskId)
    """
    task = await store.get_task(task_id)
    if task is None:
        raise McpError(
            ErrorData(
                code=INVALID_PARAMS,
                message=f"Task not found: {task_id}",
            )
        )

    if is_terminal(task.status):
        raise McpError(
            ErrorData(
                code=INVALID_PARAMS,
                message=f"Cannot cancel task in terminal state '{task.status}'",
            )
        )

    # Update task to cancelled status
    cancelled_task = await store.update_task(task_id, status="cancelled")
    return CancelTaskResult(**cancelled_task.model_dump())


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
    model_immediate_response: str | None = None,
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
        model_immediate_response: Optional string to include in _meta as
            io.modelcontextprotocol/model-immediate-response. This allows
            hosts to pass an immediate response to the model while the
            task executes in the background.

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
                        model_immediate_response="Processing started, this may take a while.",
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

    # Build _meta if model_immediate_response is provided
    meta: dict[str, Any] | None = None
    if model_immediate_response is not None:
        meta = {MODEL_IMMEDIATE_RESPONSE_KEY: model_immediate_response}

    return CreateTaskResult(task=task, **{"_meta": meta} if meta else {}), ctx
