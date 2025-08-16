# Streamable HTTP

Streamable HTTP is the modern transport for MCP servers, designed for production deployments with better scalability, resumability, and flexibility than SSE transport.

## Overview

Streamable HTTP offers:

- **Stateful and stateless modes** - Choose based on your scaling needs
- **Resumable connections** - Clients can reconnect and resume sessions
- **Event sourcing** - Built-in event store for reliability
- **JSON or SSE responses** - Flexible response formats
- **Better performance** - Optimized for high-throughput scenarios

## Basic usage

### Simple streamable HTTP server

```python
from mcp.server.fastmcp import FastMCP

# Create server
mcp = FastMCP(\"Streamable Server\")

@mcp.tool()
def calculate(expression: str) -> float:
    \"\"\"Safely evaluate mathematical expressions.\"\"\"
    # Simple calculator (in production, use a proper math parser)
    allowed = set('0123456789+-*/.() ')
    if not all(c in allowed for c in expression):
        raise ValueError(\"Invalid characters in expression\")
    
    try:
        result = eval(expression)
        return float(result)
    except Exception as e:
        raise ValueError(f\"Cannot evaluate expression: {e}\")

# Run with streamable HTTP transport
if __name__ == \"__main__\":
    mcp.run(transport=\"streamable-http\", host=\"0.0.0.0\", port=8000)
```

Access the server at `http://localhost:8000/mcp`

## Configuration options

### Stateful vs stateless

```python
# Stateful server (default) - maintains session state
mcp_stateful = FastMCP(\"Stateful Server\")

# Stateless server - no session persistence, better for scaling
mcp_stateless = FastMCP(\"Stateless Server\", stateless_http=True)

# Stateless with JSON responses only (no SSE)
mcp_json = FastMCP(\"JSON Server\", stateless_http=True, json_response=True)
```

### Custom paths and ports

```python
mcp = FastMCP(
    \"Custom Server\",
    host=\"0.0.0.0\",
    port=3001,
    mount_path=\"/api/mcp\",        # Custom MCP endpoint
    sse_path=\"/events\",           # Custom SSE endpoint
)

# Server available at:
# - http://localhost:3001/api/mcp (MCP endpoint)
# - http://localhost:3001/events (SSE endpoint)
```

## Client connections

### HTTP client example

```python
\"\"\"
Example HTTP client for streamable HTTP servers.
\"\"\"

import asyncio
import aiohttp
import json

async def call_mcp_tool():
    \"\"\"Call MCP tool via HTTP.\"\"\"
    url = \"http://localhost:8000/mcp\"
    
    # Initialize connection
    init_request = {
        \"method\": \"initialize\",
        \"params\": {
            \"protocolVersion\": \"2025-06-18\",
            \"clientInfo\": {
                \"name\": \"HTTP Client\",
                \"version\": \"1.0.0\"
            },
            \"capabilities\": {}
        }
    }
    
    async with aiohttp.ClientSession() as session:
        # Initialize
        async with session.post(url, json=init_request) as response:
            init_result = await response.json()
            print(f\"Initialize: {init_result}\")
        
        # List tools
        list_request = {
            \"method\": \"tools/list\",
            \"params\": {}
        }
        
        async with session.post(url, json=list_request) as response:
            tools_result = await response.json()
            print(f\"Tools: {tools_result}\")
        
        # Call tool
        call_request = {
            \"method\": \"tools/call\",
            \"params\": {
                \"name\": \"calculate\",
                \"arguments\": {\"expression\": \"2 + 3 * 4\"}
            }
        }
        
        async with session.post(url, json=call_request) as response:
            call_result = await response.json()
            print(f\"Result: {call_result}\")

if __name__ == \"__main__\":
    asyncio.run(call_mcp_tool())
```

### Using the MCP client library

```python
\"\"\"
Connect to streamable HTTP server using MCP client library.
\"\"\"

import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def connect_to_server():
    \"\"\"Connect using MCP client library.\"\"\"
    
    async with streamablehttp_client(\"http://localhost:8000/mcp\") as (read, write, _):
        async with ClientSession(read, write) as session:
            # Initialize connection
            await session.initialize()
            
            # List available tools
            tools = await session.list_tools()
            print(f\"Available tools: {[tool.name for tool in tools.tools]}\")
            
            # Call a tool
            result = await session.call_tool(\"calculate\", {\"expression\": \"10 / 2\"})
            content = result.content[0]
            if hasattr(content, 'text'):
                print(f\"Calculation result: {content.text}\")

if __name__ == \"__main__\":
    asyncio.run(connect_to_server())
```

## Mounting to existing applications

### Starlette integration

```python
\"\"\"
Mount multiple MCP servers in a Starlette application.
\"\"\"

import contextlib
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

# Create specialized servers
auth_server = FastMCP(\"Auth Server\", stateless_http=True)
data_server = FastMCP(\"Data Server\", stateless_http=True)

@auth_server.tool()
def login(username: str, password: str) -> dict:
    \"\"\"Authenticate user.\"\"\"
    # Simple auth (use proper authentication in production)
    if username == \"admin\" and password == \"secret\":
        return {\"token\": \"auth-token-123\", \"expires\": 3600}
    raise ValueError(\"Invalid credentials\")

@data_server.tool()
def get_data(query: str) -> list[dict]:
    \"\"\"Retrieve data based on query.\"\"\"
    # Mock data
    return [{\"id\": 1, \"data\": f\"Result for {query}\"}]

# Health check endpoint
async def health_check(request):
    return JSONResponse({\"status\": \"healthy\"})

# Combined lifespan manager
@contextlib.asynccontextmanager
async def lifespan(app):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(auth_server.session_manager.run())
        await stack.enter_async_context(data_server.session_manager.run())
        yield

# Create Starlette app
app = Starlette(
    routes=[
        Route(\"/health\", health_check),
        Mount(\"/auth\", auth_server.streamable_http_app()),
        Mount(\"/data\", data_server.streamable_http_app()),
    ],
    lifespan=lifespan
)

# Run with: uvicorn app:app --host 0.0.0.0 --port 8000
```

### FastAPI integration

```python
\"\"\"
Integrate MCP server with FastAPI.
\"\"\"

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

# Create FastAPI app
app = FastAPI(title=\"API with MCP\")

# Create MCP server
mcp = FastMCP(\"FastAPI MCP\", stateless_http=True)

@mcp.tool()
def process_request(data: str) -> dict:
    \"\"\"Process API request data.\"\"\"
    return {\"processed\": data, \"length\": len(data)}

# Regular FastAPI endpoint
@app.get(\"/\")
async def root():
    return {\"message\": \"FastAPI with MCP integration\"}

# Mount MCP server
app.mount(\"/mcp\", mcp.streamable_http_app())

# Startup event
@app.on_event(\"startup\")
async def startup():
    await mcp.session_manager.start()

# Shutdown event
@app.on_event(\"shutdown\")
async def shutdown():
    await mcp.session_manager.stop()
```

## Advanced configuration

### Event store configuration

```python
\"\"\"
Server with custom event store configuration.
\"\"\"

from mcp.server.fastmcp import FastMCP
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import aioredis

@asynccontextmanager
async def redis_lifespan(server: FastMCP) -> AsyncIterator[dict]:
    \"\"\"Configure Redis for event storage.\"\"\"
    redis = aioredis.from_url(\"redis://localhost:6379\")
    try:
        yield {\"redis\": redis}
    finally:
        await redis.close()

# Create server with event store
mcp = FastMCP(
    \"Event Store Server\",
    lifespan=redis_lifespan,
    stateless_http=False  # Stateful for event sourcing
)

@mcp.tool()
async def store_event(event_type: str, data: dict, ctx) -> str:
    \"\"\"Store an event with Redis backend.\"\"\"
    import json
    import time
    
    redis = ctx.request_context.lifespan_context[\"redis\"]
    
    event = {
        \"type\": event_type,
        \"data\": data,
        \"timestamp\": time.time(),
        \"id\": f\"event_{hash(str(data)) % 10000:04d}\"
    }
    
    # Store event in Redis
    await redis.lpush(\"events\", json.dumps(event))
    await redis.ltrim(\"events\", 0, 999)  # Keep last 1000 events
    
    return event[\"id\"]
```

### Custom middleware

```python
\"\"\"
Server with custom middleware for logging and authentication.
\"\"\"

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import time
import logging

logger = logging.getLogger(\"mcp.middleware\")

class LoggingMiddleware(BaseHTTPMiddleware):
    \"\"\"Middleware to log all requests.\"\"\"
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Log request
        logger.info(f\"Request: {request.method} {request.url.path}\")
        
        response = await call_next(request)
        
        # Log response
        duration = time.time() - start_time
        logger.info(f\"Response: {response.status_code} ({duration:.3f}s)\")
        
        return response

class AuthMiddleware(BaseHTTPMiddleware):
    \"\"\"Simple API key authentication middleware.\"\"\"
    
    async def dispatch(self, request: Request, call_next):
        # Skip auth for health checks
        if request.url.path == \"/health\":
            return await call_next(request)
        
        # Check API key
        api_key = request.headers.get(\"X-API-Key\")
        if not api_key or api_key != \"secret-key-123\":
            return Response(\"Unauthorized\", status_code=401)
        
        return await call_next(request)

# Create server with middleware
mcp = FastMCP(\"Middleware Server\")

@mcp.tool()
def protected_operation() -> str:
    \"\"\"Operation that requires authentication.\"\"\"
    return \"This operation is protected by middleware\"

# Add middleware to the ASGI app
app = mcp.streamable_http_app()
app.add_middleware(LoggingMiddleware)
app.add_middleware(AuthMiddleware)

if __name__ == \"__main__\":
    # Custom ASGI server setup
    import uvicorn
    uvicorn.run(app, host=\"0.0.0.0\", port=8000)
```

## Performance optimization

### Connection pooling

```python
\"\"\"
High-performance server with connection pooling.
\"\"\"

import asyncpg
import aioredis
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass

@dataclass
class PerformanceContext:
    db_pool: asyncpg.Pool
    redis_pool: aioredis.ConnectionPool

@asynccontextmanager
async def performance_lifespan(server: FastMCP) -> AsyncIterator[PerformanceContext]:
    \"\"\"High-performance lifespan with connection pools.\"\"\"
    
    # Database connection pool
    db_pool = await asyncpg.create_pool(
        \"postgresql://user:pass@localhost/db\",
        min_size=10,
        max_size=50,
        max_queries=50000,
        max_inactive_connection_lifetime=300,
    )
    
    # Redis connection pool
    redis_pool = aioredis.ConnectionPool.from_url(
        \"redis://localhost:6379\",
        max_connections=20
    )
    
    try:
        yield PerformanceContext(db_pool=db_pool, redis_pool=redis_pool)
    finally:
        await db_pool.close()
        redis_pool.disconnect()

# Optimized server configuration
mcp = FastMCP(
    \"High Performance Server\",
    lifespan=performance_lifespan,
    stateless_http=True,  # Better for horizontal scaling
    json_response=True,   # Disable SSE for pure HTTP
    host=\"0.0.0.0\",
    port=8000
)

@mcp.tool()
async def fast_query(sql: str, ctx) -> list[dict]:
    \"\"\"Execute database query using connection pool.\"\"\"
    context = ctx.request_context.lifespan_context
    
    async with context.db_pool.acquire() as conn:
        rows = await conn.fetch(sql)
        return [dict(row) for row in rows]

@mcp.tool()
async def cache_operation(key: str, value: str, ctx) -> str:
    \"\"\"Cache operation using Redis pool.\"\"\"
    context = ctx.request_context.lifespan_context
    
    redis = aioredis.Redis(connection_pool=context.redis_pool)
    await redis.set(key, value, ex=3600)  # 1 hour expiration
    
    return f\"Cached {key} = {value}\"
```

### Load balancing setup

```yaml
# docker-compose.yml for load-balanced setup
version: '3.8'

services:
  nginx:
    image: nginx:alpine
    ports:
      - \"80:80\"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - mcp-server-1
      - mcp-server-2

  mcp-server-1:
    build: .
    environment:
      - INSTANCE_ID=server-1
      - PORT=8000
    
  mcp-server-2:
    build: .
    environment:
      - INSTANCE_ID=server-2
      - PORT=8000

  redis:
    image: redis:alpine
    
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: mcpdb
      POSTGRES_USER: mcpuser
      POSTGRES_PASSWORD: mcppass
```

Nginx configuration for load balancing:

```nginx
# nginx.conf
events {
    worker_connections 1024;
}

http {
    upstream mcp_servers {
        server mcp-server-1:8000;
        server mcp-server-2:8000;
    }
    
    server {
        listen 80;
        
        location /mcp {
            proxy_pass http://mcp_servers;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection \"upgrade\";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }
    }
}
```

## Monitoring and debugging

### Health checks and metrics

```python
@mcp.tool()
async def server_metrics() -> dict:
    \"\"\"Get server performance metrics.\"\"\"
    import psutil
    import time
    
    process = psutil.Process()
    
    return {
        \"memory\": {
            \"rss\": process.memory_info().rss,
            \"vms\": process.memory_info().vms,
            \"percent\": process.memory_percent()
        },
        \"cpu\": {
            \"percent\": process.cpu_percent(),
            \"times\": process.cpu_times()._asdict()
        },
        \"connections\": len(process.connections()),
        \"uptime\": time.time() - process.create_time(),
        \"threads\": process.num_threads()
    }

@mcp.tool()
async def connection_info(ctx) -> dict:
    \"\"\"Get information about current connection.\"\"\"
    return {
        \"request_id\": ctx.request_id,
        \"client_id\": ctx.client_id,
        \"server_name\": ctx.fastmcp.name,
        \"transport\": \"streamable-http\",
        \"stateless\": ctx.fastmcp.settings.stateless_http
    }
```

### Request tracing

```python
import uuid
from starlette.middleware.base import BaseHTTPMiddleware

class TracingMiddleware(BaseHTTPMiddleware):
    \"\"\"Add tracing to all requests.\"\"\"
    
    async def dispatch(self, request: Request, call_next):
        # Generate trace ID
        trace_id = str(uuid.uuid4())
        request.state.trace_id = trace_id
        
        # Add to response headers
        response = await call_next(request)
        response.headers[\"X-Trace-ID\"] = trace_id
        
        return response

@mcp.tool()
async def traced_operation(data: str, ctx) -> dict:
    \"\"\"Operation with distributed tracing.\"\"\"
    # In a real implementation, you'd get trace_id from request context
    trace_id = f\"trace_{hash(data) % 10000:04d}\"
    
    await ctx.info(f\"[{trace_id}] Processing operation\")
    
    result = {\"processed\": data, \"trace_id\": trace_id}
    
    await ctx.info(f\"[{trace_id}] Operation completed\")
    
    return result
```

## Testing streamable HTTP servers

### Integration testing

```python
\"\"\"
Integration tests for streamable HTTP server.
\"\"\"

import pytest
import asyncio
import aiohttp
from mcp.server.fastmcp import FastMCP

@pytest.fixture
async def test_server():
    \"\"\"Create test server.\"\"\"
    mcp = FastMCP(\"Test Server\")
    
    @mcp.tool()
    def test_tool(value: str) -> str:
        return f\"Test: {value}\"
    
    # Start server in background
    server_task = asyncio.create_task(
        mcp.run_async(transport=\"streamable-http\", port=8999)
    )
    
    # Wait for server to start
    await asyncio.sleep(0.1)
    
    yield \"http://localhost:8999/mcp\"
    
    # Cleanup
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass

@pytest.mark.asyncio
async def test_server_connection(test_server):
    \"\"\"Test basic server connectivity.\"\"\"
    url = test_server
    
    async with aiohttp.ClientSession() as session:
        # Test initialization
        init_request = {
            \"method\": \"initialize\",
            \"params\": {
                \"protocolVersion\": \"2025-06-18\",
                \"clientInfo\": {\"name\": \"Test Client\", \"version\": \"1.0.0\"},
                \"capabilities\": {}
            }
        }
        
        async with session.post(url, json=init_request) as response:
            assert response.status == 200
            result = await response.json()
            assert \"result\" in result

@pytest.mark.asyncio
async def test_tool_call(test_server):
    \"\"\"Test tool invocation.\"\"\"
    url = test_server
    
    async with aiohttp.ClientSession() as session:
        # Call tool
        call_request = {
            \"method\": \"tools/call\",
            \"params\": {
                \"name\": \"test_tool\",
                \"arguments\": {\"value\": \"hello\"}
            }
        }
        
        async with session.post(url, json=call_request) as response:
            assert response.status == 200
            result = await response.json()
            assert \"result\" in result
```

## Best practices

### Deployment guidelines

- **Use stateless mode** for horizontal scaling
- **Enable connection pooling** for database and cache operations
- **Implement health checks** for load balancer integration
- **Add proper logging** with structured output and trace IDs
- **Use reverse proxy** (nginx/Apache) for SSL termination and load balancing

### Performance tips

- **Choose stateless mode** for better scalability
- **Use connection pools** for external services
- **Implement caching** for expensive operations
- **Monitor resource usage** with metrics endpoints
- **Optimize database queries** and use proper indexing

### Security considerations

- **Use HTTPS** in production
- **Implement authentication** middleware
- **Validate inputs** thoroughly
- **Rate limit** requests to prevent abuse
- **Log security events** for monitoring

## Next steps

- **[ASGI integration](asgi-integration.md)** - Integrate with web frameworks
- **[Running servers](running-servers.md)** - Production deployment strategies
- **[Authentication](authentication.md)** - Secure your HTTP endpoints
- **[Client development](writing-clients.md)** - Build HTTP clients