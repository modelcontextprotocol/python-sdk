# Simple Task Client

A minimal MCP client demonstrating polling for task results over streamable HTTP.

## Running

First, start the simple-task server in another terminal:

```bash
cd examples/servers/simple-task
uv run mcp-simple-task
```

Then run the client:

```bash
cd examples/clients/simple-task-client
uv run mcp-simple-task-client
```

Use `--url` to connect to a different server.

## What it does

1. Connects to the server via streamable HTTP
2. Calls the `long_running_task` tool as a task
3. Polls the task status until completion
4. Retrieves and prints the result

## Expected output

```text
Available tools: ['long_running_task']

Calling tool as a task...
Task created: <task-id>
  Status: working - Starting work...
  Status: working - Processing step 1...
  Status: working - Processing step 2...
  Status: completed -

Result: Task completed!
```
