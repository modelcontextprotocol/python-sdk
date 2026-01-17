# StreamableHTTP MCP Server Implementation Guide

## Overview

There are two primary approaches to implementing StreamableHTTP MCP servers in Python:

1. **FastMCP (High-Level)** - Recommended for most use cases
2. **Low-Level Server** - For advanced use cases requiring fine-grained control

This guide helps you understand when to use each approach.

---

## FastMCP (High-Level Implementation)

### When to Use FastMCP

✅ **Use FastMCP when you need:**

- **Quick development** - Get a server running in minutes
- **Standard features** - Built-in auth, routing, middleware
- **Multiple servers** - Easy to mount multiple MCP servers in one app
- **Best practices** - Automatically follows MCP conventions
- **Simple configuration** - Decorator-based API for tools, resources, prompts
- **Production deployment** - Built-in support for stateless/stateful modes

### FastMCP Features

```python
from mcp.server.fastmcp import FastMCP

# Stateful server (maintains session state)
mcp = FastMCP("MyServer")

# Stateless server (for load-balanced deployments)
# mcp = FastMCP("MyServer", stateless_http=True)

# JSON-only responses (no SSE streaming)
# mcp = FastMCP("MyServer", stateless_http=True, json_response=True)

@mcp.tool()
def my_tool(arg: str) -> str:
    """Simple tool definition"""
    return f"Processed: {arg}"

# Run standalone
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

### Key Advantages

1. **Automatic Session Management**
   - FastMCP handles session creation, cleanup, and lifecycle
   - Built-in support for stateful and stateless modes

2. **Easy Mounting**
   ```python
   from starlette.applications import Starlette
   from starlette.routing import Mount
   
   # Mount multiple servers
   app = Starlette(
       routes=[
           Mount("/api", app=api_mcp.streamable_http_app()),
           Mount("/chat", app=chat_mcp.streamable_http_app()),
       ]
   )
   ```

3. **Path Configuration**
   ```python
   # Default: endpoints at /mcp
   mcp = FastMCP("Server")
   
   # Custom: endpoints at root
   mcp = FastMCP("Server", streamable_http_path="/")
   
   # Can also configure later
   mcp.settings.streamable_http_path = "/custom"
   ```

4. **Built-in Features**
   - Authentication middleware
   - CORS handling
   - Error handling
   - Health checks
   - Logging

### FastMCP Examples

**Basic Usage:**
```python
# examples/snippets/servers/streamable_http_basic_mounting.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("My App")

@mcp.tool()
def hello() -> str:
    return "Hello from MCP!"

# Mount in Starlette
app = Starlette(
    routes=[Mount("/", app=mcp.streamable_http_app())]
)
```

**Multiple Servers:**
```python
# examples/snippets/servers/streamable_http_multiple_servers.py
api_mcp = FastMCP("API Server")
chat_mcp = FastMCP("Chat Server")

# Configure to mount at root
api_mcp.settings.streamable_http_path = "/"
chat_mcp.settings.streamable_http_path = "/"

app = Starlette(
    routes=[
        Mount("/api", app=api_mcp.streamable_http_app()),
        Mount("/chat", app=chat_mcp.streamable_http_app()),
    ]
)
```

**Stateless Mode (Load Balancing):**
```python
# examples/snippets/servers/streamable_config.py
# Stateless server for multi-node deployments
mcp = FastMCP("StatelessServer", stateless_http=True)

# Or stateless with JSON-only (no SSE)
mcp = FastMCP("StatelessServer", stateless_http=True, json_response=True)
```

---

## Low-Level Server Implementation

### When to Use Low-Level

✅ **Use Low-Level Server when you need:**

- **Custom event stores** - Implement resumability with custom storage (Redis, DB)
- **Fine-grained control** - Full control over session management
- **Custom middleware** - Specific ASGI middleware stack
- **Advanced routing** - Complex routing requirements
- **Custom protocols** - Non-standard MCP extensions
- **Performance tuning** - Optimize for specific use cases

### Low-Level Features

```python
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette

# Create MCP server
app = Server("my-server")

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    # Handle tool calls
    return [{"type": "text", "text": "Result"}]

# Create session manager
session_manager = StreamableHTTPSessionManager(
    app=app,
    event_store=my_custom_event_store,  # Custom implementation
    json_response=False,
    stateless=False
)

# Create ASGI handler
async def handle_streamable_http(scope, receive, send):
    await session_manager.handle_request(scope, receive, send)

# Create Starlette app
starlette_app = Starlette(
    routes=[Mount("/mcp", app=handle_streamable_http)],
    lifespan=lambda app: session_manager.run()
)
```

### Key Advantages

1. **Custom Event Storage**
   ```python
   from mcp.server.streamable_http import EventStore
   
   class RedisEventStore(EventStore):
       """Custom event store using Redis for resumability"""
       async def store_event(self, stream_id, event_id, event):
           # Store in Redis
           pass
       
       async def replay_events(self, stream_id, last_event_id):
           # Replay from Redis
           pass
   
   event_store = RedisEventStore()
   session_manager = StreamableHTTPSessionManager(
       app=app,
       event_store=event_store
   )
   ```

2. **Direct Session Control**
   ```python
   # Full control over session lifecycle
   @contextlib.asynccontextmanager
   async def lifespan(app: Starlette):
       async with session_manager.run():
           logger.info("Server started")
           yield
           logger.info("Server shutting down")
   ```

3. **Custom Middleware Stack**
   ```python
   # Add custom middleware layers
   from starlette.middleware import Middleware
   from custom_middleware import RateLimitMiddleware, MetricsMiddleware
   
   starlette_app = Starlette(
       routes=[Mount("/mcp", app=handle_streamable_http)],
       middleware=[
           Middleware(RateLimitMiddleware),
           Middleware(MetricsMiddleware),
           Middleware(CORSMiddleware, allow_origins=["*"]),
       ],
       lifespan=lifespan
   )
   ```

4. **Advanced Configuration**
   ```python
   # Stateless mode with custom settings
   session_manager = StreamableHTTPSessionManager(
       app=app,
       event_store=None,  # No event store for stateless
       json_response=True,  # JSON-only responses
       stateless=True,  # Stateless mode
   )
   ```

### Low-Level Examples

**Stateful Server with Custom Event Store:**
```python
# examples/servers/simple-streamablehttp/
from .event_store import InMemoryEventStore

# Custom event store for resumability
event_store = InMemoryEventStore()

session_manager = StreamableHTTPSessionManager(
    app=app,
    event_store=event_store,
    json_response=False
)
```

**Stateless Server (No Session State):**
```python
# examples/servers/simple-streamablehttp-stateless/
session_manager = StreamableHTTPSessionManager(
    app=app,
    event_store=None,  # No event store needed
    json_response=False,
    stateless=True
)
```

**Custom Notifications:**
```python
@app.call_tool()
async def call_tool(name: str, arguments: dict):
    ctx = app.request_context
    
    # Send notifications with related_request_id
    await ctx.session.send_log_message(
        level="info",
        data="Processing...",
        logger="my-tool",
        related_request_id=ctx.request_id  # Tie to current request
    )
    
    # Or send to GET SSE stream (server-initiated)
    await ctx.session.send_resource_updated(uri="resource://updated")
    
    return result
```

---

## Feature Comparison

| Feature | FastMCP | Low-Level |
|---------|---------|-----------|
| **Development Speed** | ⚡ Fast (minutes) | 🔧 Slower (hours) |
| **Learning Curve** | 📚 Easy | 📚📚 Moderate |
| **Code Lines** | 📝 ~10-20 lines | 📝📝 ~50-100 lines |
| **Session Management** | ✅ Automatic | 🔧 Manual |
| **Event Store** | ⚠️ Not exposed | ✅ Full control |
| **Middleware** | ✅ Built-in | ✅ Full control |
| **Auth Support** | ✅ Built-in | 🔧 Manual |
| **Multiple Servers** | ✅ Easy mounting | 🔧 Manual routing |
| **Stateless Mode** | ✅ Simple flag | ✅ Manual config |
| **Custom Protocols** | ❌ Limited | ✅ Full control |
| **Production Ready** | ✅ Yes | ✅ Yes (with more work) |

---

## Decision Matrix

### Choose FastMCP if:

- ✅ You want to build quickly
- ✅ You need standard MCP features
- ✅ You're mounting multiple servers
- ✅ You want built-in auth/middleware
- ✅ You don't need custom event storage
- ✅ You're new to MCP development

### Choose Low-Level if:

- ✅ You need custom event store (Redis, DB, etc.)
- ✅ You need fine-grained session control
- ✅ You have specific middleware requirements
- ✅ You're implementing custom MCP extensions
- ✅ You need to optimize performance
- ✅ You want full control over the stack

---

## Common Patterns

### Pattern 1: Start with FastMCP, Extend Later

Most projects should start with FastMCP. If you later need custom features:

```python
# Start simple
mcp = FastMCP("MyServer")

# Later, access the session manager for advanced features
session_manager = mcp.session_manager

# Or get the low-level MCP server
low_level_server = mcp._mcp_server
```

### Pattern 2: Hybrid Approach

Use FastMCP for most servers, Low-Level for specialized ones:

```python
# FastMCP for standard API
api_mcp = FastMCP("API")

# Low-Level for custom resumability
custom_server = Server("Custom")
custom_manager = StreamableHTTPSessionManager(
    app=custom_server,
    event_store=RedisEventStore()
)

# Mount both
app = Starlette(
    routes=[
        Mount("/api", app=api_mcp.streamable_http_app()),
        Mount("/custom", app=lambda s, r, se: custom_manager.handle_request(s, r, se)),
    ]
)
```

### Pattern 3: FastMCP with Custom Event Store

If you only need a custom event store, you can inject it:

```python
mcp = FastMCP("MyServer")

# Inject custom event store before calling streamable_http_app()
mcp._event_store = RedisEventStore()

# Now create the app
app = mcp.streamable_http_app()
```

---

## Deployment Considerations

### Stateful vs Stateless

**Stateful (Session-based):**
- Best for: Single-node deployments, development
- Pros: Supports resumability, maintains context
- Cons: Sticky sessions required for load balancing
- FastMCP: `FastMCP("Server")`  # Default
- Low-Level: `stateless=False`

**Stateless (Request-based):**
- Best for: Multi-node deployments, high availability
- Pros: Easy load balancing, horizontal scaling
- Cons: No resumability, no session context
- FastMCP: `FastMCP("Server", stateless_http=True)`
- Low-Level: `stateless=True`

### SSE vs JSON Response

**SSE Streaming:**
- Best for: Real-time notifications, progress updates
- Pros: Streaming responses, resumability support
- Cons: More complex client implementation
- FastMCP: `json_response=False`  # Default
- Low-Level: `json_response=False`

**JSON-only:**
- Best for: Simple request/response, REST APIs
- Pros: Simple clients, standard HTTP
- Cons: No streaming, no resumability
- FastMCP: `FastMCP("Server", json_response=True)`
- Low-Level: `json_response=True`

---

## Examples in This Repository

### FastMCP Examples

1. **Basic Mounting**: `examples/snippets/servers/streamable_http_basic_mounting.py`
2. **Multiple Servers**: `examples/snippets/servers/streamable_http_multiple_servers.py`
3. **Path Configuration**: `examples/snippets/servers/streamable_http_path_config.py`
4. **Host-based Routing**: `examples/snippets/servers/streamable_http_host_mounting.py`
5. **Complete Example**: `examples/snippets/servers/streamable_http_complete.py`
6. **Config Options**: `examples/snippets/servers/streamable_config.py`

### Low-Level Examples

1. **Stateful Server**: `examples/servers/simple-streamablehttp/`
   - Custom event store (InMemoryEventStore)
   - Resumability support
   - Notifications with related_request_id

2. **Stateless Server**: `examples/servers/simple-streamablehttp-stateless/`
   - No session state
   - Multi-node ready
   - Simple deployment

---

## Migration Guide

### From Low-Level to FastMCP

Before (Low-Level):
```python
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

app = Server("my-server")

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    return [{"type": "text", "text": "Result"}]

session_manager = StreamableHTTPSessionManager(app=app)
# ... more setup code
```

After (FastMCP):
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("my-server")

@mcp.tool()
def my_tool(name: str) -> str:
    return "Result"

# That's it!
mcp.run(transport="streamable-http")
```

---

## Best Practices

### General Guidelines

1. **Start with FastMCP** unless you have specific requirements
2. **Use stateless mode** for production deployments with load balancing
3. **Implement event stores** for resumability in stateful mode
4. **Add proper logging** for debugging and monitoring
5. **Configure CORS** appropriately for browser clients
6. **Use SSL/TLS** in production

### Security

1. **Don't expose internal endpoints** publicly
2. **Validate all inputs** in tool handlers
3. **Use authentication** for production servers
4. **Restrict CORS origins** in production
5. **Rate limit** requests

### Performance

1. **Use stateless mode** for horizontal scaling
2. **Implement caching** for expensive operations
3. **Use async/await** properly
4. **Monitor resource usage**
5. **Set appropriate timeouts**

---

## Troubleshooting

### Common Issues

**Issue**: Server exits immediately with no logs
- **Solution**: Check if module is importable, verify entry point

**Issue**: 406 Not Acceptable errors
- **Solution**: Ensure Accept header includes both `application/json` and `text/event-stream`

**Issue**: Session not persisting
- **Solution**: Use stateful mode (`stateless=False`) and provide event store

**Issue**: Can't connect from outside Docker
- **Solution**: Bind to `0.0.0.0` instead of `127.0.0.1`

**Issue**: Events not replaying
- **Solution**: Ensure event store is provided and Last-Event-ID header is sent

---

## Conclusion

**TL;DR:**

- **Use FastMCP** for 90% of use cases - it's fast, simple, and production-ready
- **Use Low-Level** when you need custom event stores or fine-grained control
- **Start simple** and add complexity only when needed
- **Both approaches** are production-ready and fully supported

For more information, see:
- [Official MCP Documentation](https://modelcontextprotocol.io/docs)
