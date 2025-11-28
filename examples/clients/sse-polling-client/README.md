# MCP SSE Polling Demo Client

Demonstrates client-side auto-reconnect for the SSE polling pattern (SEP-1699).

## Features

- Connects to SSE polling demo server
- Automatically reconnects when server closes SSE stream
- Resumes from Last-Event-ID to avoid missing messages
- Respects server-provided retry interval

## Usage

```bash
# First start the server:
uv run mcp-sse-polling-demo --port 3000

# Then run this client:
uv run mcp-sse-polling-client --url http://localhost:3000/mcp

# Custom options:
uv run mcp-sse-polling-client --url http://localhost:3000/mcp --items 20 --checkpoint-every 5
```

## Options

- `--url`: Server URL (default: <http://localhost:3000/mcp>)
- `--items`: Number of items to process (default: 10)
- `--checkpoint-every`: Checkpoint interval (default: 3)
- `--log-level`: Logging level (default: DEBUG)
