# MCP Simple StreamableHttp Stateless Server Example

A stateless MCP server example demonstrating the StreamableHttp transport without maintaining session state. This example is ideal for understanding how to deploy MCP servers in multi-node environments where requests can be routed to any instance.

## Features

- Uses the StreamableHTTP transport in stateless mode (mcp_session_id=None)
- Each request creates a new ephemeral connection
- No session state maintained between requests
- Task lifecycle scoped to individual requests
- Suitable for deployment in multi-node environments

## Key Differences from Stateful Version

1. **No Session Management**: The server explicitly sets `mcp_session_id=None` when creating the transport
2. **Request Scoped**: Each request creates its own server instance and task group
3. **Immediate Cleanup**: Resources are cleaned up after each request completes
4. **Rejcts Session IDs**: If a client sends a session ID, the server rejects it with a BAD_REQUEST
5. **Stateless Deployments**: Can be deployed to multiple nodes behind a load balancer

## Usage

Start the server:

```bash
# Using default port 3000
uv run mcp-simple-streamablehttp-stateless

# Using custom port
uv run mcp-simple-streamablehttp-stateless --port 3000

# Custom logging level
uv run mcp-simple-streamablehttp-stateless --log-level DEBUG

# Enable JSON responses instead of SSE streams
uv run mcp-simple-streamablehttp-stateless --json-response
```

The server exposes a tool named "start-notification-stream" that accepts three arguments:

- `interval`: Time between notifications in seconds (e.g., 1.0)
- `count`: Number of notifications to send (e.g., 5)
- `caller`: Identifier string for the caller

## Client Considerations

When connecting to a stateless server:
1. Do not send the `X-MCP-Session-ID` header
2. Each request is independent with no shared state
3. Suitable for one-shot operations or when state can be maintained client-side
4. Works well with load balancers that distribute requests across multiple instances

## Deployment Benefits

1. **Horizontal Scaling**: Deploy multiple instances behind a load balancer
2. **No Session Affinity**: Requests can be routed to any instance
3. **Simplified Infrastructure**: No session storage or sticky sessions required
4. **Cloud Native**: Works well in containerized and serverless environments

## Client

You can connect to this server using an HTTP client. For now, only the TypeScript SDK has streamable HTTP client examples, or you can use [Inspector](https://github.com/modelcontextprotocol/inspector) for testing.