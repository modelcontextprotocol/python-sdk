# Client Task Usage

!!! warning "Experimental"

    Tasks are an experimental feature. The API may change without notice.

This guide covers calling task-augmented tools from clients, handling the `input_required` status, and advanced patterns like receiving task requests from servers.

## Quick Start

Call a tool as a task and poll for the result:

```python
from mcp.client.session import ClientSession
from mcp.types import CallToolResult

async with ClientSession(read, write) as session:
    await session.initialize()

    # Call tool as task
    result = await session.experimental.call_tool_as_task(
        "process_data",
        {"input": "hello"},
        ttl=60000,
    )
    task_id = result.task.taskId

    # Poll until complete
    async for status in session.experimental.poll_task(task_id):
        print(f"Status: {status.status} - {status.statusMessage or ''}")

    # Get result
    final = await session.experimental.get_task_result(task_id, CallToolResult)
    print(f"Result: {final.content[0].text}")
```

## Calling Tools as Tasks

Use `call_tool_as_task()` to invoke a tool with task augmentation:

```python
result = await session.experimental.call_tool_as_task(
    "my_tool",           # Tool name
    {"arg": "value"},    # Arguments
    ttl=60000,           # Time-to-live in milliseconds
    meta={"key": "val"}, # Optional metadata
)

task_id = result.task.taskId
print(f"Task: {task_id}, Status: {result.task.status}")
```

The response is a `CreateTaskResult` containing:

- `task.taskId` - Unique identifier for polling
- `task.status` - Initial status (usually `"working"`)
- `task.pollInterval` - Suggested polling interval (milliseconds)
- `task.ttl` - Time-to-live for results
- `task.createdAt` - Creation timestamp

## Polling with poll_task

The `poll_task()` async iterator polls until the task reaches a terminal state:

```python
async for status in session.experimental.poll_task(task_id):
    print(f"Status: {status.status}")
    if status.statusMessage:
        print(f"Progress: {status.statusMessage}")
```

It automatically:

- Respects the server's suggested `pollInterval`
- Stops when status is `completed`, `failed`, or `cancelled`
- Yields each status for progress display

### Handling input_required

When a task needs user input (elicitation), it transitions to `input_required`. You must call `get_task_result()` to receive and respond to the elicitation:

```python
async for status in session.experimental.poll_task(task_id):
    print(f"Status: {status.status}")

    if status.status == "input_required":
        # This delivers the elicitation and waits for completion
        final = await session.experimental.get_task_result(task_id, CallToolResult)
        break
```

The elicitation callback (set during session creation) handles the actual user interaction.

## Elicitation Callbacks

To handle elicitation requests from the server, provide a callback when creating the session:

```python
from mcp.types import ElicitRequestParams, ElicitResult

async def handle_elicitation(context, params: ElicitRequestParams) -> ElicitResult:
    # Display the message to the user
    print(f"Server asks: {params.message}")

    # Collect user input (this is a simplified example)
    response = input("Your response (y/n): ")
    confirmed = response.lower() == "y"

    return ElicitResult(
        action="accept",
        content={"confirm": confirmed},
    )

async with ClientSession(
    read,
    write,
    elicitation_callback=handle_elicitation,
) as session:
    await session.initialize()
    # ... call tasks that may require elicitation
```

## Sampling Callbacks

Similarly, handle sampling requests with a callback:

```python
from mcp.types import CreateMessageRequestParams, CreateMessageResult, TextContent

async def handle_sampling(context, params: CreateMessageRequestParams) -> CreateMessageResult:
    # In a real implementation, call your LLM here
    prompt = params.messages[-1].content.text if params.messages else ""

    # Return a mock response
    return CreateMessageResult(
        role="assistant",
        content=TextContent(type="text", text=f"Response to: {prompt}"),
        model="my-model",
    )

async with ClientSession(
    read,
    write,
    sampling_callback=handle_sampling,
) as session:
    # ...
```

## Retrieving Results

Once a task completes, retrieve the result:

```python
if status.status == "completed":
    result = await session.experimental.get_task_result(task_id, CallToolResult)
    for content in result.content:
        if hasattr(content, "text"):
            print(content.text)

elif status.status == "failed":
    print(f"Task failed: {status.statusMessage}")

elif status.status == "cancelled":
    print("Task was cancelled")
```

The result type matches the original request:

- `tools/call` → `CallToolResult`
- `sampling/createMessage` → `CreateMessageResult`
- `elicitation/create` → `ElicitResult`

## Cancellation

Cancel a running task:

```python
cancel_result = await session.experimental.cancel_task(task_id)
print(f"Cancelled, status: {cancel_result.status}")
```

Note: Cancellation is cooperative—the server must check for and handle cancellation.

## Listing Tasks

View all tasks on the server:

```python
result = await session.experimental.list_tasks()
for task in result.tasks:
    print(f"{task.taskId}: {task.status}")

# Handle pagination
while result.nextCursor:
    result = await session.experimental.list_tasks(cursor=result.nextCursor)
    for task in result.tasks:
        print(f"{task.taskId}: {task.status}")
```

## Advanced: Client as Task Receiver

Servers can send task-augmented requests to clients. This is useful when the server needs the client to perform async work (like complex sampling or user interaction).

### Declaring Client Capabilities

Register task handlers to declare what task-augmented requests your client accepts:

```python
from mcp.client.experimental.task_handlers import ExperimentalTaskHandlers
from mcp.types import (
    CreateTaskResult, GetTaskResult, GetTaskPayloadResult,
    TaskMetadata, ElicitRequestParams,
)
from mcp.shared.experimental.tasks import InMemoryTaskStore

# Client-side task store
client_store = InMemoryTaskStore()

async def handle_augmented_elicitation(context, params: ElicitRequestParams, task_metadata: TaskMetadata):
    """Handle task-augmented elicitation from server."""
    # Create a task for this elicitation
    task = await client_store.create_task(task_metadata)

    # Start async work (e.g., show UI, wait for user)
    async def complete_elicitation():
        # ... do async work ...
        result = ElicitResult(action="accept", content={"confirm": True})
        await client_store.store_result(task.taskId, result)
        await client_store.update_task(task.taskId, status="completed")

    context.session._task_group.start_soon(complete_elicitation)

    # Return task reference immediately
    return CreateTaskResult(task=task)

async def handle_get_task(context, params):
    """Handle tasks/get from server."""
    task = await client_store.get_task(params.taskId)
    return GetTaskResult(
        taskId=task.taskId,
        status=task.status,
        statusMessage=task.statusMessage,
        createdAt=task.createdAt,
        lastUpdatedAt=task.lastUpdatedAt,
        ttl=task.ttl,
        pollInterval=100,
    )

async def handle_get_task_result(context, params):
    """Handle tasks/result from server."""
    result = await client_store.get_result(params.taskId)
    return GetTaskPayloadResult.model_validate(result.model_dump())

task_handlers = ExperimentalTaskHandlers(
    augmented_elicitation=handle_augmented_elicitation,
    get_task=handle_get_task,
    get_task_result=handle_get_task_result,
)

async with ClientSession(
    read,
    write,
    experimental_task_handlers=task_handlers,
) as session:
    # Client now accepts task-augmented elicitation from server
    await session.initialize()
```

This enables flows where:

1. Client calls a task-augmented tool
2. Server's tool work calls `task.elicit_as_task()`
3. Client receives task-augmented elicitation
4. Client creates its own task, does async work
5. Server polls client's task
6. Eventually both tasks complete

## Complete Example

A client that handles all task scenarios:

```python
import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, ElicitRequestParams, ElicitResult


async def elicitation_callback(context, params: ElicitRequestParams) -> ElicitResult:
    print(f"\n[Elicitation] {params.message}")
    response = input("Confirm? (y/n): ")
    return ElicitResult(action="accept", content={"confirm": response.lower() == "y"})


async def main():
    async with stdio_client(command="python", args=["server.py"]) as (read, write):
        async with ClientSession(
            read,
            write,
            elicitation_callback=elicitation_callback,
        ) as session:
            await session.initialize()

            # List available tools
            tools = await session.list_tools()
            print("Tools:", [t.name for t in tools.tools])

            # Call a task-augmented tool
            print("\nCalling task tool...")
            result = await session.experimental.call_tool_as_task(
                "confirm_action",
                {"action": "delete files"},
            )
            task_id = result.task.taskId
            print(f"Task created: {task_id}")

            # Poll and handle input_required
            async for status in session.experimental.poll_task(task_id):
                print(f"Status: {status.status}")

                if status.status == "input_required":
                    final = await session.experimental.get_task_result(task_id, CallToolResult)
                    print(f"Result: {final.content[0].text}")
                    break

            if status.status == "completed":
                final = await session.experimental.get_task_result(task_id, CallToolResult)
                print(f"Result: {final.content[0].text}")


if __name__ == "__main__":
    anyio.run(main)
```

## Error Handling

Handle task errors gracefully:

```python
from mcp.shared.exceptions import McpError

try:
    result = await session.experimental.call_tool_as_task("my_tool", args)
    task_id = result.task.taskId

    async for status in session.experimental.poll_task(task_id):
        if status.status == "failed":
            raise RuntimeError(f"Task failed: {status.statusMessage}")

    final = await session.experimental.get_task_result(task_id, CallToolResult)

except McpError as e:
    print(f"MCP error: {e.error.message}")
except Exception as e:
    print(f"Error: {e}")
```

## Next Steps

- [Server Implementation](tasks-server.md) - Build task-supporting servers
- [Tasks Overview](tasks.md) - Review lifecycle and concepts
