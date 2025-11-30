# Simple Interactive Task Client

A minimal MCP client demonstrating responses to interactive tasks (elicitation and sampling).

## Running

First, start the interactive task server in another terminal:

```bash
cd examples/servers/simple-task-interactive
uv run mcp-simple-task-interactive
```

Then run the client:

```bash
cd examples/clients/simple-task-interactive-client
uv run mcp-simple-task-interactive-client
```

Use `--url` to connect to a different server.

## What it does

1. Connects to the server via streamable HTTP
2. Calls `confirm_delete` - server asks for confirmation, client responds via terminal
3. Calls `write_haiku` - server requests LLM completion, client returns a hardcoded haiku

## Key concepts

### Elicitation callback

```python
async def elicitation_callback(context, params) -> ElicitResult:
    # Handle user input request from server
    return ElicitResult(action="accept", content={"confirm": True})
```

### Sampling callback

```python
async def sampling_callback(context, params) -> CreateMessageResult:
    # Handle LLM completion request from server
    return CreateMessageResult(model="...", role="assistant", content=...)
```

### Using call_tool_as_task

```python
# Call a tool as a task (returns immediately with task reference)
result = await session.experimental.call_tool_as_task("tool_name", {"arg": "value"})
task_id = result.task.taskId

# Get result - this delivers elicitation/sampling requests and blocks until complete
final = await session.experimental.get_task_result(task_id, CallToolResult)
```

**Important**: The `get_task_result()` call is what triggers the delivery of elicitation
and sampling requests to your callbacks. It blocks until the task completes and returns
the final result.

## Expected output

```text
Available tools: ['confirm_delete', 'write_haiku']

--- Demo 1: Elicitation ---
Calling confirm_delete tool...
Task created: <task-id>

[Elicitation] Server asks: Are you sure you want to delete 'important.txt'?
Your response (y/n): y
[Elicitation] Responding with: confirm=True
Result: Deleted 'important.txt'

--- Demo 2: Sampling ---
Calling write_haiku tool...
Task created: <task-id>

[Sampling] Server requests LLM completion for: Write a haiku about autumn leaves
[Sampling] Responding with haiku
Result:
Haiku:
Cherry blossoms fall
Softly on the quiet pond
Spring whispers goodbye
```
