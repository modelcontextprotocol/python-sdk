# Server Task Implementation

!!! warning "Experimental"

    Tasks are an experimental feature. The API may change without notice.

This guide covers implementing task support in MCP servers, from basic setup to advanced patterns like elicitation and sampling within tasks.

## Quick Start

The simplest way to add task support:

```python
from mcp.server import Server
from mcp.server.experimental.task_context import ServerTaskContext
from mcp.types import CallToolResult, CreateTaskResult, TextContent, Tool, ToolExecution, TASK_REQUIRED

server = Server("my-server")
server.experimental.enable_tasks()  # Registers all task handlers automatically

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="process_data",
            description="Process data asynchronously",
            inputSchema={"type": "object", "properties": {"input": {"type": "string"}}},
            execution=ToolExecution(taskSupport=TASK_REQUIRED),
        )
    ]

@server.call_tool()
async def handle_tool(name: str, arguments: dict) -> CallToolResult | CreateTaskResult:
    if name == "process_data":
        return await handle_process_data(arguments)
    return CallToolResult(content=[TextContent(type="text", text=f"Unknown: {name}")], isError=True)

async def handle_process_data(arguments: dict) -> CreateTaskResult:
    ctx = server.request_context
    ctx.experimental.validate_task_mode(TASK_REQUIRED)

    async def work(task: ServerTaskContext) -> CallToolResult:
        await task.update_status("Processing...")
        result = arguments.get("input", "").upper()
        return CallToolResult(content=[TextContent(type="text", text=result)])

    return await ctx.experimental.run_task(work)
```

That's it. `enable_tasks()` automatically:

- Creates an in-memory task store
- Registers handlers for `tasks/get`, `tasks/result`, `tasks/list`, `tasks/cancel`
- Updates server capabilities

## Tool Declaration

Tools declare task support via the `execution.taskSupport` field:

```python
from mcp.types import Tool, ToolExecution, TASK_REQUIRED, TASK_OPTIONAL, TASK_FORBIDDEN

Tool(
    name="my_tool",
    inputSchema={"type": "object"},
    execution=ToolExecution(taskSupport=TASK_REQUIRED),  # or TASK_OPTIONAL, TASK_FORBIDDEN
)
```

| Value | Meaning |
|-------|---------|
| `TASK_REQUIRED` | Tool **must** be called as a task |
| `TASK_OPTIONAL` | Tool supports both sync and task execution |
| `TASK_FORBIDDEN` | Tool **cannot** be called as a task (default) |

Validate the request matches your tool's requirements:

```python
@server.call_tool()
async def handle_tool(name: str, arguments: dict):
    ctx = server.request_context

    if name == "required_task_tool":
        ctx.experimental.validate_task_mode(TASK_REQUIRED)  # Raises if not task mode
        return await handle_as_task(arguments)

    elif name == "optional_task_tool":
        if ctx.experimental.is_task:
            return await handle_as_task(arguments)
        else:
            return handle_sync(arguments)
```

## The run_task Pattern

`run_task()` is the recommended way to execute task work:

```python
async def handle_my_tool(arguments: dict) -> CreateTaskResult:
    ctx = server.request_context
    ctx.experimental.validate_task_mode(TASK_REQUIRED)

    async def work(task: ServerTaskContext) -> CallToolResult:
        # Your work here
        return CallToolResult(content=[TextContent(type="text", text="Done")])

    return await ctx.experimental.run_task(work)
```

**What `run_task()` does:**

1. Creates a task in the store
2. Spawns your work function in the background
3. Returns `CreateTaskResult` immediately
4. Auto-completes the task when your function returns
5. Auto-fails the task if your function raises

**The `ServerTaskContext` provides:**

- `task.task_id` - The task identifier
- `task.update_status(message)` - Update progress
- `task.complete(result)` - Explicitly complete (usually automatic)
- `task.fail(error)` - Explicitly fail
- `task.is_cancelled` - Check if cancellation requested

## Status Updates

Keep clients informed of progress:

```python
async def work(task: ServerTaskContext) -> CallToolResult:
    await task.update_status("Starting...")

    for i, item in enumerate(items):
        await task.update_status(f"Processing {i+1}/{len(items)}")
        await process_item(item)

    await task.update_status("Finalizing...")
    return CallToolResult(content=[TextContent(type="text", text="Complete")])
```

Status messages appear in `tasks/get` responses, letting clients show progress to users.

## Elicitation Within Tasks

Tasks can request user input via elicitation. This transitions the task to `input_required` status.

### Form Elicitation

Collect structured data from the user:

```python
async def work(task: ServerTaskContext) -> CallToolResult:
    await task.update_status("Waiting for confirmation...")

    result = await task.elicit(
        message="Delete these files?",
        requestedSchema={
            "type": "object",
            "properties": {
                "confirm": {"type": "boolean"},
                "reason": {"type": "string"},
            },
            "required": ["confirm"],
        },
    )

    if result.action == "accept" and result.content.get("confirm"):
        # User confirmed
        return CallToolResult(content=[TextContent(type="text", text="Files deleted")])
    else:
        # User declined or cancelled
        return CallToolResult(content=[TextContent(type="text", text="Cancelled")])
```

### URL Elicitation

Direct users to external URLs for OAuth, payments, or other out-of-band flows:

```python
async def work(task: ServerTaskContext) -> CallToolResult:
    await task.update_status("Waiting for OAuth...")

    result = await task.elicit_url(
        message="Please authorize with GitHub",
        url="https://github.com/login/oauth/authorize?client_id=...",
        elicitation_id="oauth-github-123",
    )

    if result.action == "accept":
        # User completed OAuth flow
        return CallToolResult(content=[TextContent(type="text", text="Connected to GitHub")])
    else:
        return CallToolResult(content=[TextContent(type="text", text="OAuth cancelled")])
```

## Sampling Within Tasks

Tasks can request LLM completions from the client:

```python
from mcp.types import SamplingMessage, TextContent

async def work(task: ServerTaskContext) -> CallToolResult:
    await task.update_status("Generating response...")

    result = await task.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text="Write a haiku about coding"),
            )
        ],
        max_tokens=100,
    )

    haiku = result.content.text if isinstance(result.content, TextContent) else "Error"
    return CallToolResult(content=[TextContent(type="text", text=haiku)])
```

Sampling supports additional parameters:

```python
result = await task.create_message(
    messages=[...],
    max_tokens=500,
    system_prompt="You are a helpful assistant",
    temperature=0.7,
    stop_sequences=["\n\n"],
    model_preferences=ModelPreferences(hints=[ModelHint(name="claude-3")]),
)
```

## Cancellation Support

Check for cancellation in long-running work:

```python
async def work(task: ServerTaskContext) -> CallToolResult:
    for i in range(1000):
        if task.is_cancelled:
            # Clean up and exit
            return CallToolResult(content=[TextContent(type="text", text="Cancelled")])

        await task.update_status(f"Step {i}/1000")
        await process_step(i)

    return CallToolResult(content=[TextContent(type="text", text="Complete")])
```

The SDK's default cancel handler updates the task status. Your work function should check `is_cancelled` periodically.

## Custom Task Store

For production, implement `TaskStore` with persistent storage:

```python
from mcp.shared.experimental.tasks.store import TaskStore
from mcp.types import Task, TaskMetadata, Result

class RedisTaskStore(TaskStore):
    def __init__(self, redis_client):
        self.redis = redis_client

    async def create_task(self, metadata: TaskMetadata, task_id: str | None = None) -> Task:
        # Create and persist task
        ...

    async def get_task(self, task_id: str) -> Task | None:
        # Retrieve task from Redis
        ...

    async def update_task(self, task_id: str, status: str | None = None, ...) -> Task:
        # Update and persist
        ...

    async def store_result(self, task_id: str, result: Result) -> None:
        # Store result in Redis
        ...

    async def get_result(self, task_id: str) -> Result | None:
        # Retrieve result
        ...

    # ... implement remaining methods
```

Use your custom store:

```python
store = RedisTaskStore(redis_client)
server.experimental.enable_tasks(store=store)
```

## Complete Example

A server with multiple task-supporting tools:

```python
from mcp.server import Server
from mcp.server.experimental.task_context import ServerTaskContext
from mcp.types import (
    CallToolResult, CreateTaskResult, TextContent, Tool, ToolExecution,
    SamplingMessage, TASK_REQUIRED,
)

server = Server("task-demo")
server.experimental.enable_tasks()


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="confirm_action",
            description="Requires user confirmation",
            inputSchema={"type": "object", "properties": {"action": {"type": "string"}}},
            execution=ToolExecution(taskSupport=TASK_REQUIRED),
        ),
        Tool(
            name="generate_text",
            description="Generate text via LLM",
            inputSchema={"type": "object", "properties": {"prompt": {"type": "string"}}},
            execution=ToolExecution(taskSupport=TASK_REQUIRED),
        ),
    ]


async def handle_confirm_action(arguments: dict) -> CreateTaskResult:
    ctx = server.request_context
    ctx.experimental.validate_task_mode(TASK_REQUIRED)

    action = arguments.get("action", "unknown action")

    async def work(task: ServerTaskContext) -> CallToolResult:
        result = await task.elicit(
            message=f"Confirm: {action}?",
            requestedSchema={
                "type": "object",
                "properties": {"confirm": {"type": "boolean"}},
                "required": ["confirm"],
            },
        )

        if result.action == "accept" and result.content.get("confirm"):
            return CallToolResult(content=[TextContent(type="text", text=f"Executed: {action}")])
        return CallToolResult(content=[TextContent(type="text", text="Cancelled")])

    return await ctx.experimental.run_task(work)


async def handle_generate_text(arguments: dict) -> CreateTaskResult:
    ctx = server.request_context
    ctx.experimental.validate_task_mode(TASK_REQUIRED)

    prompt = arguments.get("prompt", "Hello")

    async def work(task: ServerTaskContext) -> CallToolResult:
        await task.update_status("Generating...")

        result = await task.create_message(
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text=prompt))],
            max_tokens=200,
        )

        text = result.content.text if isinstance(result.content, TextContent) else "Error"
        return CallToolResult(content=[TextContent(type="text", text=text)])

    return await ctx.experimental.run_task(work)


@server.call_tool()
async def handle_tool(name: str, arguments: dict) -> CallToolResult | CreateTaskResult:
    if name == "confirm_action":
        return await handle_confirm_action(arguments)
    elif name == "generate_text":
        return await handle_generate_text(arguments)
    return CallToolResult(content=[TextContent(type="text", text=f"Unknown: {name}")], isError=True)
```

## Error Handling in Tasks

Tasks handle errors automatically, but you can also fail explicitly:

```python
async def work(task: ServerTaskContext) -> CallToolResult:
    try:
        result = await risky_operation()
        return CallToolResult(content=[TextContent(type="text", text=result)])
    except PermissionError:
        await task.fail("Access denied - insufficient permissions")
        raise
    except TimeoutError:
        await task.fail("Operation timed out after 30 seconds")
        raise
```

When `run_task()` catches an exception, it automatically:

1. Marks the task as `failed`
2. Sets `statusMessage` to the exception message
3. Propagates the exception (which is caught by the task group)

For custom error messages, call `task.fail()` before raising.

## HTTP Transport Example

For web applications, use the Streamable HTTP transport:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server import Server
from mcp.server.experimental.task_context import ServerTaskContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import (
    CallToolResult, CreateTaskResult, TextContent, Tool, ToolExecution, TASK_REQUIRED,
)


server = Server("http-task-server")
server.experimental.enable_tasks()


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="long_operation",
            description="A long-running operation",
            inputSchema={"type": "object", "properties": {"duration": {"type": "number"}}},
            execution=ToolExecution(taskSupport=TASK_REQUIRED),
        )
    ]


async def handle_long_operation(arguments: dict) -> CreateTaskResult:
    ctx = server.request_context
    ctx.experimental.validate_task_mode(TASK_REQUIRED)

    duration = arguments.get("duration", 5)

    async def work(task: ServerTaskContext) -> CallToolResult:
        import anyio
        for i in range(int(duration)):
            await task.update_status(f"Step {i+1}/{int(duration)}")
            await anyio.sleep(1)
        return CallToolResult(content=[TextContent(type="text", text=f"Completed after {duration}s")])

    return await ctx.experimental.run_task(work)


@server.call_tool()
async def handle_tool(name: str, arguments: dict) -> CallToolResult | CreateTaskResult:
    if name == "long_operation":
        return await handle_long_operation(arguments)
    return CallToolResult(content=[TextContent(type="text", text=f"Unknown: {name}")], isError=True)


def create_app():
    session_manager = StreamableHTTPSessionManager(app=server)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    return Starlette(
        routes=[Mount("/mcp", app=session_manager.handle_request)],
        lifespan=lifespan,
    )


if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
```

## Testing Task Servers

Test task functionality with the SDK's testing utilities:

```python
import pytest
import anyio
from mcp.client.session import ClientSession
from mcp.types import CallToolResult


@pytest.mark.anyio
async def test_task_tool():
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream(10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream(10)

    async def run_server():
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options(),
        )

    async def run_client():
        async with ClientSession(server_to_client_receive, client_to_server_send) as session:
            await session.initialize()

            # Call the tool as a task
            result = await session.experimental.call_tool_as_task("my_tool", {"arg": "value"})
            task_id = result.task.taskId
            assert result.task.status == "working"

            # Poll until complete
            async for status in session.experimental.poll_task(task_id):
                if status.status in ("completed", "failed"):
                    break

            # Get result
            final = await session.experimental.get_task_result(task_id, CallToolResult)
            assert len(final.content) > 0

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)
        tg.start_soon(run_client)
```

## Best Practices

### Keep Work Functions Focused

```python
# Good: focused work function
async def work(task: ServerTaskContext) -> CallToolResult:
    await task.update_status("Validating...")
    validate_input(arguments)

    await task.update_status("Processing...")
    result = await process_data(arguments)

    return CallToolResult(content=[TextContent(type="text", text=result)])
```

### Check Cancellation in Loops

```python
async def work(task: ServerTaskContext) -> CallToolResult:
    results = []
    for item in large_dataset:
        if task.is_cancelled:
            return CallToolResult(content=[TextContent(type="text", text="Cancelled")])

        results.append(await process(item))

    return CallToolResult(content=[TextContent(type="text", text=str(results))])
```

### Use Meaningful Status Messages

```python
async def work(task: ServerTaskContext) -> CallToolResult:
    await task.update_status("Connecting to database...")
    db = await connect()

    await task.update_status("Fetching records (0/1000)...")
    for i, record in enumerate(records):
        if i % 100 == 0:
            await task.update_status(f"Processing records ({i}/1000)...")
        await process(record)

    await task.update_status("Finalizing results...")
    return CallToolResult(content=[TextContent(type="text", text="Done")])
```

### Handle Elicitation Responses

```python
async def work(task: ServerTaskContext) -> CallToolResult:
    result = await task.elicit(message="Continue?", requestedSchema={...})

    match result.action:
        case "accept":
            # User accepted, process content
            return await process_accepted(result.content)
        case "decline":
            # User explicitly declined
            return CallToolResult(content=[TextContent(type="text", text="User declined")])
        case "cancel":
            # User cancelled the elicitation
            return CallToolResult(content=[TextContent(type="text", text="Cancelled")])
```

## Next Steps

- [Client Usage](tasks-client.md) - Learn how clients interact with task servers
- [Tasks Overview](tasks.md) - Review lifecycle and concepts
