# Simple Interactive Task Server

A minimal MCP server demonstrating interactive tasks with elicitation and sampling.

## Running

```bash
cd examples/servers/simple-task-interactive
uv run mcp-simple-task-interactive
```

The server starts on `http://localhost:8000/mcp` by default. Use `--port` to change.

## What it does

This server exposes two tools:

### `confirm_delete` (demonstrates elicitation)

Asks the user for confirmation before "deleting" a file.

- Uses `task.elicit()` to request user input
- Shows the elicitation flow: task -> input_required -> response -> complete

### `write_haiku` (demonstrates sampling)

Asks the LLM to write a haiku about a topic.

- Uses `task.create_message()` to request LLM completion
- Shows the sampling flow: task -> input_required -> response -> complete

## Usage with the client

In one terminal, start the server:

```bash
cd examples/servers/simple-task-interactive
uv run mcp-simple-task-interactive
```

In another terminal, run the interactive client:

```bash
cd examples/clients/simple-task-interactive-client
uv run mcp-simple-task-interactive-client
```

## Expected server output

When a client connects and calls the tools, you'll see:

```text
Starting server on http://localhost:8000/mcp

[Server] confirm_delete called for 'important.txt'
[Server] Task created: <task-id>
[Server] Sending elicitation request to client...
[Server] Received elicitation response: action=accept, content={'confirm': True}
[Server] Completing task with result: Deleted 'important.txt'

[Server] write_haiku called for topic 'autumn leaves'
[Server] Task created: <task-id>
[Server] Sending sampling request to client...
[Server] Received sampling response: Cherry blossoms fall
Softly on the quiet pon...
[Server] Completing task with haiku
```

## Key concepts

1. **ServerTaskContext**: Provides `elicit()` and `create_message()` for user interaction
2. **run_task()**: Spawns background work, auto-completes/fails, returns immediately
3. **TaskResultHandler**: Delivers queued messages and routes responses
4. **Response routing**: Responses are routed back to waiting resolvers
