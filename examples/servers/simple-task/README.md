# Simple Task Server

A minimal MCP server demonstrating the experimental tasks feature over streamable HTTP.

## Running

```bash
cd examples/servers/simple-task
uv run mcp-simple-task
```

The server starts on `http://localhost:8000/mcp` by default. Use `--port` to change.

## What it does

This server exposes a single tool `long_running_task` that:

1. Must be called as a task (with `task` metadata in the request)
2. Takes ~3 seconds to complete
3. Sends status updates during execution
4. Returns a result when complete

## Usage with the client

In one terminal, start the server:

```bash
cd examples/servers/simple-task
uv run mcp-simple-task
```

In another terminal, run the client:

```bash
cd examples/clients/simple-task-client
uv run mcp-simple-task-client
```
