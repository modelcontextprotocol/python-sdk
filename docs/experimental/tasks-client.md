# Client Task Usage

!!! warning "Experimental"

    Tasks are an experimental feature. The API may change without notice.

This guide shows how to call task-augmented tools from an MCP client and retrieve
their results.

## Prerequisites

You'll need:

- An MCP client session connected to a server that supports tasks
- The `ClientSession` from `mcp.client.session`

## Step 1: Call a Tool as a Task

Use the `experimental.call_tool_as_task()` method to call a tool with task
augmentation:

```python
from mcp.client.session import ClientSession

async with ClientSession(read_stream, write_stream) as session:
    await session.initialize()

    # Call the tool as a task
    result = await session.experimental.call_tool_as_task(
        "process_data",
        {"input": "hello world"},
        ttl=60000,  # Keep result for 60 seconds
    )

    # Get the task ID for polling
    task_id = result.task.taskId
    print(f"Task created: {task_id}")
    print(f"Initial status: {result.task.status}")
```

The method returns a `CreateTaskResult` containing:

- `task.taskId` - Unique identifier for polling
- `task.status` - Initial status (usually "working")
- `task.pollInterval` - Suggested polling interval in milliseconds
- `task.ttl` - Time-to-live for the task result

## Step 2: Poll for Status

Check the task status periodically until it completes:

```python
import anyio

while True:
    status = await session.experimental.get_task(task_id)
    print(f"Status: {status.status}")

    if status.statusMessage:
        print(f"Message: {status.statusMessage}")

    if status.status in ("completed", "failed", "cancelled"):
        break

    # Respect the suggested poll interval
    poll_interval = status.pollInterval or 500
    await anyio.sleep(poll_interval / 1000)  # Convert ms to seconds
```

The `GetTaskResult` contains:

- `taskId` - The task identifier
- `status` - Current status: "working", "completed", "failed", "cancelled", or "input_required"
- `statusMessage` - Optional progress message
- `pollInterval` - Suggested interval before next poll (milliseconds)

## Step 3: Retrieve the Result

Once the task is complete, retrieve the actual result:

```python
from mcp.types import CallToolResult

if status.status == "completed":
    # Get the actual tool result
    final_result = await session.experimental.get_task_result(
        task_id,
        CallToolResult,  # The expected result type
    )

    # Process the result
    for content in final_result.content:
        if hasattr(content, "text"):
            print(f"Result: {content.text}")

elif status.status == "failed":
    print(f"Task failed: {status.statusMessage}")
```

The result type depends on the original request:

- `tools/call` tasks return `CallToolResult`
- Other request types return their corresponding result type

## Complete Polling Example

Here's a complete client that calls a task and waits for the result:

```python
import anyio

from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult


async def main():
    async with stdio_client(
        command="python",
        args=["server.py"],
    ) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. Create the task
            print("Creating task...")
            result = await session.experimental.call_tool_as_task(
                "slow_echo",
                {"message": "Hello, Tasks!", "delay_seconds": 3},
            )
            task_id = result.task.taskId
            print(f"Task created: {task_id}")

            # 2. Poll until complete
            print("Polling for completion...")
            while True:
                status = await session.experimental.get_task(task_id)
                print(f"  Status: {status.status}", end="")
                if status.statusMessage:
                    print(f" - {status.statusMessage}", end="")
                print()

                if status.status in ("completed", "failed", "cancelled"):
                    break

                await anyio.sleep((status.pollInterval or 500) / 1000)

            # 3. Get the result
            if status.status == "completed":
                print("Retrieving result...")
                final = await session.experimental.get_task_result(
                    task_id,
                    CallToolResult,
                )
                for content in final.content:
                    if hasattr(content, "text"):
                        print(f"Result: {content.text}")
            else:
                print(f"Task ended with status: {status.status}")


if __name__ == "__main__":
    anyio.run(main)
```

## Cancelling Tasks

If you need to cancel a running task:

```python
cancel_result = await session.experimental.cancel_task(task_id)
print(f"Task cancelled, final status: {cancel_result.status}")
```

Note that cancellation is cooperative - the server must check for and handle
cancellation requests. A cancelled task will transition to the "cancelled" state.

## Listing Tasks

To see all tasks on a server:

```python
# Get the first page of tasks
tasks_result = await session.experimental.list_tasks()

for task in tasks_result.tasks:
    print(f"Task {task.taskId}: {task.status}")

# Handle pagination if needed
while tasks_result.nextCursor:
    tasks_result = await session.experimental.list_tasks(
        cursor=tasks_result.nextCursor
    )
    for task in tasks_result.tasks:
        print(f"Task {task.taskId}: {task.status}")
```

## Low-Level API

If you need more control, you can use the low-level request API directly:

```python
from mcp.types import (
    ClientRequest,
    CallToolRequest,
    CallToolRequestParams,
    TaskMetadata,
    CreateTaskResult,
    GetTaskRequest,
    GetTaskRequestParams,
    GetTaskResult,
    GetTaskPayloadRequest,
    GetTaskPayloadRequestParams,
)

# Create task with full control over the request
result = await session.send_request(
    ClientRequest(
        CallToolRequest(
            params=CallToolRequestParams(
                name="process_data",
                arguments={"input": "data"},
                task=TaskMetadata(ttl=60000),
            ),
        )
    ),
    CreateTaskResult,
)

# Poll status
status = await session.send_request(
    ClientRequest(
        GetTaskRequest(
            params=GetTaskRequestParams(taskId=result.task.taskId),
        )
    ),
    GetTaskResult,
)

# Get result
final = await session.send_request(
    ClientRequest(
        GetTaskPayloadRequest(
            params=GetTaskPayloadRequestParams(taskId=result.task.taskId),
        )
    ),
    CallToolResult,
)
```

## Error Handling

Tasks can fail for various reasons. Handle errors appropriately:

```python
try:
    result = await session.experimental.call_tool_as_task("my_tool", args)
    task_id = result.task.taskId

    while True:
        status = await session.experimental.get_task(task_id)

        if status.status == "completed":
            final = await session.experimental.get_task_result(
                task_id, CallToolResult
            )
            # Process success...
            break

        elif status.status == "failed":
            print(f"Task failed: {status.statusMessage}")
            break

        elif status.status == "cancelled":
            print("Task was cancelled")
            break

        await anyio.sleep(0.5)

except Exception as e:
    print(f"Error: {e}")
```

## Next Steps

- [Server Implementation](tasks-server.md) - Learn how to build task-supporting servers
- [Tasks Overview](tasks.md) - Review the task lifecycle and concepts
