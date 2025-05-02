# MCP Simple StreamableHttp Server Example

A simple MCP server example demonstrating the StreamableHttp transport, which enables HTTP-based communication with MCP servers using streaming.

## Features

- Uses the StreamableHTTP transport for server-client communication
- Supports REST API operations (POST, GET, DELETE) for `/mcp` endpoint
- Task management with anyio task groups
- Ability to send multiple notifications over time to the client
- Proper resource cleanup and lifespan management
- Resumability support via InMemoryEventStore

## Usage

Start the server on the default or custom port:

```bash

# Using custom port
uv run mcp-simple-streamablehttp --port 3000

# Custom logging level
uv run mcp-simple-streamablehttp --log-level DEBUG

# Enable JSON responses instead of SSE streams
uv run mcp-simple-streamablehttp --json-response
```

The server exposes a tool named "start-notification-stream" that accepts three arguments:

- `interval`: Time between notifications in seconds (e.g., 1.0)
- `count`: Number of notifications to send (e.g., 5)
- `caller`: Identifier string for the caller

## Resumability Support

This server includes resumability support through the InMemoryEventStore. This enables clients to:

- Reconnect to the server after a disconnection
- Resume event streaming from where they left off using the Last-Event-ID header


The server will:
- Generate unique event IDs for each SSE message
- Store events in memory for later replay
- Replay missed events when a client reconnects with a Last-Event-ID header

Note: The InMemoryEventStore is designed for demonstration purposes only. For production use, consider implementing a persistent storage solution.



## Client

You can connect to this server using an HTTP client, for now only Typescript SDK has streamable HTTP client examples or you can use [Inspector](https://github.com/modelcontextprotocol/inspector)