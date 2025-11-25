# Tasks

!!! warning "Experimental"

    Tasks are an experimental feature tracking the draft MCP specification.
    The API may change without notice.

Tasks allow MCP servers to handle requests asynchronously. When a client sends a
task-augmented request, the server can start working in the background and return
a task reference immediately. The client then polls for updates and retrieves the
result when complete.

## When to Use Tasks

Tasks are useful when operations:

- Take significant time to complete (seconds to minutes)
- May require intermediate status updates
- Need to run in the background without blocking the client

## Task Lifecycle

A task progresses through these states:

```text
working → completed
        → failed
        → cancelled

working → input_required → working → completed/failed/cancelled
```

| State | Description |
|-------|-------------|
| `working` | The task is being processed |
| `input_required` | The server needs additional information |
| `completed` | The task finished successfully |
| `failed` | The task encountered an error |
| `cancelled` | The task was cancelled |

Once a task reaches `completed`, `failed`, or `cancelled`, it cannot transition
to any other state.

## Basic Flow

Here's the typical interaction pattern:

1. **Client** sends a tool call with task metadata
2. **Server** creates a task, spawns background work, returns `CreateTaskResult`
3. **Client** receives the task ID and starts polling
4. **Server** executes the work, updating status as needed
5. **Client** polls with `tasks/get` to check status
6. **Server** finishes work and stores the result
7. **Client** retrieves result with `tasks/result`

```text
Client                                 Server
   │                                      │
   │──── tools/call (with task) ─────────>│
   │                                      │ create task
   │<──── CreateTaskResult ──────────────│ spawn work
   │                                      │
   │──── tasks/get ──────────────────────>│
   │<──── status: working ───────────────│
   │                                      │ ... work continues ...
   │──── tasks/get ──────────────────────>│
   │<──── status: completed ─────────────│
   │                                      │
   │──── tasks/result ───────────────────>│
   │<──── CallToolResult ────────────────│
   │                                      │
```

## Key Concepts

### Task Metadata

When a client wants a request handled as a task, it includes `TaskMetadata` in
the request:

```python
task = TaskMetadata(ttl=60000)  # TTL in milliseconds
```

The `ttl` (time-to-live) specifies how long the task and its result should be
retained after completion.

### Task Store

Servers need to persist task state somewhere. The SDK provides an abstract
`TaskStore` interface and an `InMemoryTaskStore` for development:

```python
from mcp.shared.experimental.tasks import InMemoryTaskStore

store = InMemoryTaskStore()
```

The store tracks:

- Task state (status, messages, timestamps)
- Results for completed tasks
- Automatic cleanup based on TTL

For production, you'd implement `TaskStore` with a database or distributed cache.

### Capabilities

Task support is advertised through server capabilities. The SDK automatically
updates capabilities when you register task handlers:

```python
# This registers the handler AND advertises the capability
@server.experimental.get_task()
async def handle_get_task(request: GetTaskRequest) -> GetTaskResult:
    ...
```

## Next Steps

- [Server Implementation](tasks-server.md) - How to add task support to your server
- [Client Usage](tasks-client.md) - How to call and poll tasks from a client
