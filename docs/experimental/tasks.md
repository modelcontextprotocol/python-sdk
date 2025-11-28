# Tasks

!!! warning "Experimental"

    Tasks are an experimental feature tracking the draft MCP specification.
    The API may change without notice.

Tasks enable asynchronous request handling in MCP. Instead of blocking until an operation completes, the receiver creates a task, returns immediately, and the requestor polls for the result.

## When to Use Tasks

Tasks are designed for operations that:

- Take significant time (seconds to minutes)
- Need progress updates during execution
- Require user input mid-execution (elicitation, sampling)
- Should run without blocking the requestor

Common use cases:

- Long-running data processing
- Multi-step workflows with user confirmation
- LLM-powered operations requiring sampling
- OAuth flows requiring user browser interaction

## Task Lifecycle

```text
                    ┌─────────────┐
                    │   working   │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
     ┌────────────┐  ┌───────────┐  ┌───────────┐
     │ completed  │  │  failed   │  │ cancelled │
     └────────────┘  └───────────┘  └───────────┘
              ▲
              │
     ┌────────┴────────┐
     │ input_required  │◄──────┐
     └────────┬────────┘       │
              │                │
              └────────────────┘
```

| Status | Description |
|--------|-------------|
| `working` | Task is being processed |
| `input_required` | Receiver needs input from requestor (elicitation/sampling) |
| `completed` | Task finished successfully |
| `failed` | Task encountered an error |
| `cancelled` | Task was cancelled by requestor |

Terminal states (`completed`, `failed`, `cancelled`) are final—tasks cannot transition out of them.

## Bidirectional Flow

Tasks work in both directions:

**Client → Server** (most common):

```text
Client                              Server
  │                                    │
  │── tools/call (task) ──────────────>│ Creates task
  │<── CreateTaskResult ───────────────│
  │                                    │
  │── tasks/get ──────────────────────>│
  │<── status: working ────────────────│
  │                                    │ ... work continues ...
  │── tasks/get ──────────────────────>│
  │<── status: completed ──────────────│
  │                                    │
  │── tasks/result ───────────────────>│
  │<── CallToolResult ─────────────────│
```

**Server → Client** (for elicitation/sampling):

```text
Server                              Client
  │                                    │
  │── elicitation/create (task) ──────>│ Creates task
  │<── CreateTaskResult ───────────────│
  │                                    │
  │── tasks/get ──────────────────────>│
  │<── status: working ────────────────│
  │                                    │ ... user interaction ...
  │── tasks/get ──────────────────────>│
  │<── status: completed ──────────────│
  │                                    │
  │── tasks/result ───────────────────>│
  │<── ElicitResult ───────────────────│
```

## Key Concepts

### Task Metadata

When augmenting a request with task execution, include `TaskMetadata`:

```python
from mcp.types import TaskMetadata

task = TaskMetadata(ttl=60000)  # TTL in milliseconds
```

The `ttl` (time-to-live) specifies how long the task and result are retained after completion.

### Task Store

Servers persist task state in a `TaskStore`. The SDK provides `InMemoryTaskStore` for development:

```python
from mcp.shared.experimental.tasks import InMemoryTaskStore

store = InMemoryTaskStore()
```

For production, implement `TaskStore` with a database or distributed cache.

### Capabilities

Both servers and clients declare task support through capabilities:

**Server capabilities:**

- `tasks.requests.tools.call` - Server accepts task-augmented tool calls

**Client capabilities:**

- `tasks.requests.sampling.createMessage` - Client accepts task-augmented sampling
- `tasks.requests.elicitation.create` - Client accepts task-augmented elicitation

The SDK manages these automatically when you enable task support.

## Quick Example

**Server** (simplified API):

```python
from mcp.server import Server
from mcp.server.experimental.task_context import ServerTaskContext
from mcp.types import CallToolResult, TextContent, TASK_REQUIRED

server = Server("my-server")
server.experimental.enable_tasks()  # One-line setup

@server.call_tool()
async def handle_tool(name: str, arguments: dict):
    ctx = server.request_context
    ctx.experimental.validate_task_mode(TASK_REQUIRED)

    async def work(task: ServerTaskContext):
        await task.update_status("Processing...")
        # ... do work ...
        return CallToolResult(content=[TextContent(type="text", text="Done!")])

    return await ctx.experimental.run_task(work)
```

**Client:**

```python
from mcp.client.session import ClientSession
from mcp.types import CallToolResult

async with ClientSession(read, write) as session:
    await session.initialize()

    # Call tool as task
    result = await session.experimental.call_tool_as_task("my_tool", {"arg": "value"})
    task_id = result.task.taskId

    # Poll until done
    async for status in session.experimental.poll_task(task_id):
        print(f"Status: {status.status}")

    # Get result
    final = await session.experimental.get_task_result(task_id, CallToolResult)
```

## Next Steps

- [Server Implementation](tasks-server.md) - Build task-supporting servers
- [Client Usage](tasks-client.md) - Call and poll tasks from clients
