# HTTP transport examples

HTTP transports enable web-based MCP server deployment with support for multiple clients and scalable architectures.

Choose HTTP transports for production deployments that need to serve multiple clients or integrate with web infrastructure.

## Transport comparison

| Feature          | Streamable HTTP    | SSE               | stdio            |
| ---------------- | ------------------ | ----------------- | ---------------- |
| **Resumability** | ✅ With event store | ❌                 | ❌                |
| **Scalability**  | ✅ Multi-client     | ✅ Multi-client    | ❌ Single process |
| **State**        | Configurable       | Session-based     | Process-based    |
| **Deployment**   | Web servers        | Web servers       | Local execution  |
| **Best for**     | Production APIs    | Real-time updates | Development/CLI  |

## Streamable HTTP configuration

Basic streamable HTTP server setup with different configurations:

```python
--8<-- "examples/snippets/servers/streamable_config.py"
```

This example demonstrates:

- **Stateful servers**: Maintain session state (default)
- **Stateless servers**: No session persistence (`stateless_http=True`)
- **JSON responses**: Disable SSE streaming (`json_response=True`)
- Transport selection at runtime

## Mounting multiple servers

Deploying multiple MCP servers in a single Starlette application:

```python
--8<-- "examples/snippets/servers/streamable_starlette_mount.py"
```

This pattern shows:

- Creating multiple FastMCP server instances
- Mounting servers at different paths (`/echo`, `/math`)
- Shared lifespan management across servers
- Combined session manager lifecycle

## Stateful HTTP server

Full low-level implementation of a stateful HTTP server:

```python
--8<-- "examples/servers/simple-streamablehttp/mcp_simple_streamablehttp/server.py"
```

This comprehensive example includes:

- Event store for resumability (reconnection support)
- Progress notifications and logging
- Resource change notifications
- Streaming tool execution with progress updates
- Production-ready ASGI integration

## Stateless HTTP server

Low-level stateless server for high-scale deployments:

```python
--8<-- "examples/servers/simple-streamablehttp-stateless/mcp_simple_streamablehttp_stateless/server.py"
```

Features of stateless design:

- No session state persistence
- Simplified architecture for load balancing
- Better horizontal scaling capabilities
- Each request is independent

## Event store implementation

Supporting resumable connections with event storage:

```python
--8<-- "examples/servers/simple-streamablehttp/mcp_simple_streamablehttp/event_store.py"
```

This component enables:

- Client reconnection with `Last-Event-ID` headers
- Event replay for missed messages
- Persistent streaming across connection interruptions
- Production-ready resumability patterns
