# Server Task Implementation

!!! warning "Experimental"

    Tasks are an experimental feature. The API may change without notice.

This guide shows how to add task support to an MCP server, starting with the
simplest case and building up to more advanced patterns.

## Prerequisites

You'll need:

- A low-level MCP server
- A task store for state management
- A task group for spawning background work

## Step 1: Basic Setup

First, set up the task store and server. The `InMemoryTaskStore` is suitable
for development and testing:

```python
from dataclasses import dataclass
from anyio.abc import TaskGroup

from mcp.server import Server
from mcp.shared.experimental.tasks import InMemoryTaskStore


@dataclass
class AppContext:
    """Application context available during request handling."""
    task_group: TaskGroup
    store: InMemoryTaskStore


server: Server[AppContext, None] = Server("my-task-server")
store = InMemoryTaskStore()
```

## Step 2: Declare Task-Supporting Tools

Tools that support tasks should declare this in their execution metadata:

```python
from mcp.types import Tool, ToolExecution, TASK_REQUIRED, TASK_OPTIONAL

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="process_data",
            description="Process data asynchronously",
            inputSchema={
                "type": "object",
                "properties": {"input": {"type": "string"}},
            },
            # TASK_REQUIRED means this tool MUST be called as a task
            execution=ToolExecution(taskSupport=TASK_REQUIRED),
        ),
    ]
```

The `taskSupport` field can be:

- `TASK_REQUIRED` ("required") - Tool must be called as a task
- `TASK_OPTIONAL` ("optional") - Tool supports both sync and task execution
- `TASK_FORBIDDEN` ("forbidden") - Tool cannot be called as a task (default)

## Step 3: Handle Tool Calls

When a client calls a tool as a task, the request context contains task metadata.
Check for this and create a task:

```python
from mcp.shared.experimental.tasks import task_execution
from mcp.types import (
    CallToolResult,
    CreateTaskResult,
    TextContent,
)


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent] | CreateTaskResult:
    ctx = server.request_context
    app = ctx.lifespan_context

    if name == "process_data" and ctx.experimental.is_task:
        # Get task metadata from the request
        task_metadata = ctx.experimental.task_metadata

        # Create the task in our store
        task = await app.store.create_task(task_metadata)

        # Define the work to do in the background
        async def do_work():
            async with task_execution(task.taskId, app.store) as task_ctx:
                # Update status to show progress
                await task_ctx.update_status("Processing input...", notify=False)

                # Do the actual work
                input_value = arguments.get("input", "")
                result_text = f"Processed: {input_value.upper()}"

                # Complete the task with the result
                await task_ctx.complete(
                    CallToolResult(
                        content=[TextContent(type="text", text=result_text)]
                    ),
                    notify=False,
                )

        # Spawn work in the background task group
        app.task_group.start_soon(do_work)

        # Return immediately with the task reference
        return CreateTaskResult(task=task)

    # Non-task execution path
    return [TextContent(type="text", text="Use task mode for this tool")]
```

Key points:

- `ctx.experimental.is_task` checks if this is a task-augmented request
- `ctx.experimental.task_metadata` contains the task configuration
- `task_execution` is a context manager that handles errors gracefully
- Work runs in a separate coroutine via the task group
- The handler returns `CreateTaskResult` immediately

## Step 4: Register Task Handlers

Clients need endpoints to query task status and retrieve results. Register these
using the experimental decorators:

```python
from mcp.types import (
    GetTaskRequest,
    GetTaskResult,
    GetTaskPayloadRequest,
    GetTaskPayloadResult,
    ListTasksRequest,
    ListTasksResult,
)


@server.experimental.get_task()
async def handle_get_task(request: GetTaskRequest) -> GetTaskResult:
    """Handle tasks/get requests - return current task status."""
    app = server.request_context.lifespan_context
    task = await app.store.get_task(request.params.taskId)

    if task is None:
        raise ValueError(f"Task {request.params.taskId} not found")

    return GetTaskResult(
        taskId=task.taskId,
        status=task.status,
        statusMessage=task.statusMessage,
        createdAt=task.createdAt,
        lastUpdatedAt=task.lastUpdatedAt,
        ttl=task.ttl,
        pollInterval=task.pollInterval,
    )


@server.experimental.get_task_result()
async def handle_get_task_result(request: GetTaskPayloadRequest) -> GetTaskPayloadResult:
    """Handle tasks/result requests - return the completed task's result."""
    app = server.request_context.lifespan_context
    result = await app.store.get_result(request.params.taskId)

    if result is None:
        raise ValueError(f"Result for task {request.params.taskId} not found")

    # Return the stored result
    assert isinstance(result, CallToolResult)
    return GetTaskPayloadResult(**result.model_dump())


@server.experimental.list_tasks()
async def handle_list_tasks(request: ListTasksRequest) -> ListTasksResult:
    """Handle tasks/list requests - return all tasks with pagination."""
    app = server.request_context.lifespan_context
    cursor = request.params.cursor if request.params else None
    tasks, next_cursor = await app.store.list_tasks(cursor=cursor)

    return ListTasksResult(tasks=tasks, nextCursor=next_cursor)
```

## Step 5: Run the Server

Wire everything together with a task group for background work:

```python
import anyio
from mcp.server.stdio import stdio_server


async def main():
    async with anyio.create_task_group() as tg:
        app = AppContext(task_group=tg, store=store)

        async with stdio_server() as (read, write):
            await server.run(
                read,
                write,
                server.create_initialization_options(),
                lifespan_context=app,
            )


if __name__ == "__main__":
    anyio.run(main)
```

## The task_execution Context Manager

The `task_execution` helper provides safe task execution:

```python
async with task_execution(task_id, store) as ctx:
    await ctx.update_status("Working...")
    result = await do_work()
    await ctx.complete(result)
```

If an exception occurs inside the context, the task is automatically marked
as failed with the exception message. This prevents tasks from getting stuck
in the "working" state.

The context provides:

- `ctx.task_id` - The task identifier
- `ctx.task` - Current task state
- `ctx.is_cancelled` - Check if cancellation was requested
- `ctx.update_status(msg)` - Update the status message
- `ctx.complete(result)` - Mark task as completed
- `ctx.fail(error)` - Mark task as failed

## Handling Cancellation

To support task cancellation, register a cancel handler and check for
cancellation in your work:

```python
from mcp.types import CancelTaskRequest, CancelTaskResult

# Track running tasks so we can cancel them
running_tasks: dict[str, TaskContext] = {}


@server.experimental.cancel_task()
async def handle_cancel_task(request: CancelTaskRequest) -> CancelTaskResult:
    task_id = request.params.taskId
    app = server.request_context.lifespan_context

    # Signal cancellation to the running work
    if task_id in running_tasks:
        running_tasks[task_id].request_cancellation()

    # Update task status
    task = await app.store.update_task(task_id, status="cancelled")

    return CancelTaskResult(
        taskId=task.taskId,
        status=task.status,
    )
```

Then check for cancellation in your work:

```python
async def do_work():
    async with task_execution(task.taskId, app.store) as ctx:
        running_tasks[task.taskId] = ctx
        try:
            for i in range(100):
                if ctx.is_cancelled:
                    return  # Exit gracefully

                await ctx.update_status(f"Processing step {i}/100")
                await process_step(i)

            await ctx.complete(result)
        finally:
            running_tasks.pop(task.taskId, None)
```

## Complete Example

Here's a full working server with task support:

```python
from dataclasses import dataclass
from typing import Any

import anyio
from anyio.abc import TaskGroup

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared.experimental.tasks import InMemoryTaskStore, task_execution
from mcp.types import (
    TASK_REQUIRED,
    CallToolResult,
    CreateTaskResult,
    GetTaskPayloadRequest,
    GetTaskPayloadResult,
    GetTaskRequest,
    GetTaskResult,
    ListTasksRequest,
    ListTasksResult,
    TextContent,
    Tool,
    ToolExecution,
)


@dataclass
class AppContext:
    task_group: TaskGroup
    store: InMemoryTaskStore


server: Server[AppContext, Any] = Server("task-example")
store = InMemoryTaskStore()


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="slow_echo",
            description="Echo input after a delay (demonstrates tasks)",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "delay_seconds": {"type": "number", "default": 2},
                },
                "required": ["message"],
            },
            execution=ToolExecution(taskSupport=TASK_REQUIRED),
        ),
    ]


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict[str, Any]
) -> list[TextContent] | CreateTaskResult:
    ctx = server.request_context
    app = ctx.lifespan_context

    if name == "slow_echo" and ctx.experimental.is_task:
        task = await app.store.create_task(ctx.experimental.task_metadata)

        async def do_work():
            async with task_execution(task.taskId, app.store) as task_ctx:
                message = arguments.get("message", "")
                delay = arguments.get("delay_seconds", 2)

                await task_ctx.update_status("Starting...", notify=False)
                await anyio.sleep(delay / 2)

                await task_ctx.update_status("Almost done...", notify=False)
                await anyio.sleep(delay / 2)

                await task_ctx.complete(
                    CallToolResult(
                        content=[TextContent(type="text", text=f"Echo: {message}")]
                    ),
                    notify=False,
                )

        app.task_group.start_soon(do_work)
        return CreateTaskResult(task=task)

    return [TextContent(type="text", text="This tool requires task mode")]


@server.experimental.get_task()
async def handle_get_task(request: GetTaskRequest) -> GetTaskResult:
    app = server.request_context.lifespan_context
    task = await app.store.get_task(request.params.taskId)
    if task is None:
        raise ValueError(f"Task not found: {request.params.taskId}")
    return GetTaskResult(
        taskId=task.taskId,
        status=task.status,
        statusMessage=task.statusMessage,
        createdAt=task.createdAt,
        lastUpdatedAt=task.lastUpdatedAt,
        ttl=task.ttl,
        pollInterval=task.pollInterval,
    )


@server.experimental.get_task_result()
async def handle_get_task_result(
    request: GetTaskPayloadRequest,
) -> GetTaskPayloadResult:
    app = server.request_context.lifespan_context
    result = await app.store.get_result(request.params.taskId)
    if result is None:
        raise ValueError(f"Result not found: {request.params.taskId}")
    assert isinstance(result, CallToolResult)
    return GetTaskPayloadResult(**result.model_dump())


@server.experimental.list_tasks()
async def handle_list_tasks(request: ListTasksRequest) -> ListTasksResult:
    app = server.request_context.lifespan_context
    cursor = request.params.cursor if request.params else None
    tasks, next_cursor = await app.store.list_tasks(cursor=cursor)
    return ListTasksResult(tasks=tasks, nextCursor=next_cursor)


async def main():
    async with anyio.create_task_group() as tg:
        app = AppContext(task_group=tg, store=store)
        async with stdio_server() as (read, write):
            await server.run(
                read,
                write,
                server.create_initialization_options(),
                lifespan_context=app,
            )


if __name__ == "__main__":
    anyio.run(main)
```

## Next Steps

- [Client Usage](tasks-client.md) - Learn how to call tasks from a client
- [Tasks Overview](tasks.md) - Review the task lifecycle and concepts
