# MCP SSE Polling Demo Server

Demonstrates the SSE polling pattern with server-initiated stream close for long-running tasks (SEP-1699).

## Features

- Priming events (automatic with EventStore)
- Server-initiated stream close via `close_sse_stream()` callback
- Client auto-reconnect with Last-Event-ID
- Progress notifications during long-running tasks
- Configurable retry interval

## Usage

```bash
# Start server on default port
uv run mcp-sse-polling-demo --port 3000

# Custom retry interval (milliseconds)
uv run mcp-sse-polling-demo --port 3000 --retry-interval 100
```

## Tool: process_batch

Processes items with periodic checkpoints that trigger SSE stream closes:

- `items`: Number of items to process (1-100, default: 10)
- `checkpoint_every`: Close stream after this many items (1-20, default: 3)

## Client

Use the companion `mcp-sse-polling-client` to test:

```bash
uv run mcp-sse-polling-client --url http://localhost:3000/mcp
```
