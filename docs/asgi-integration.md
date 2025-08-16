# ASGI integration

Learn how to integrate MCP servers with existing ASGI applications like FastAPI, Starlette, Django, and others.

## Overview

ASGI integration allows you to:

- **Mount MCP servers** in existing web applications
- **Share middleware** and authentication between HTTP and MCP endpoints
- **Unified deployment** - serve both web API and MCP from the same process
- **Resource sharing** - use the same database connections and services

## FastAPI integration

### Basic integration

```python
"""
FastAPI application with embedded MCP server.
"""

from fastapi import FastAPI, HTTPException
from mcp.server.fastmcp import FastMCP

# Create FastAPI app
app = FastAPI(title="API with MCP Integration")

# Create MCP server
mcp = FastMCP("FastAPI MCP Server", stateless_http=True)

@mcp.tool()
def process_api_data(data: str, operation: str = "uppercase") -> str:
    """Process data with various operations."""
    operations = {
        "uppercase": data.upper(),
        "lowercase": data.lower(),
        "reverse": data[::-1],
        "length": str(len(data))
    }
    
    result = operations.get(operation)
    if result is None:
        raise ValueError(f"Unknown operation: {operation}")
    
    return result

@mcp.resource("api://status")
def get_api_status() -> str:
    """Get API server status."""
    return "API server is running and healthy"

# Regular FastAPI endpoints
@app.get("/")
async def root():
    return {"message": "FastAPI with MCP integration", "mcp_endpoint": "/mcp"}

@app.get("/health")
async def health():
    return {"status": "healthy", "mcp_available": True}

@app.post("/api/process")
async def api_process(data: dict):
    """Regular API endpoint that could leverage MCP tools."""
    if "text" not in data:
        raise HTTPException(status_code=400, detail="Missing 'text' field")
    
    # In a real app, you might call MCP tools internally
    text = data["text"]
    operation = data.get("operation", "uppercase")
    
    # Simulate calling the MCP tool
    result = process_api_data(text, operation)
    
    return {"processed": result, "operation": operation}

# Mount MCP server
app.mount("/mcp", mcp.streamable_http_app())

# Lifecycle management
@app.on_event("startup")
async def startup():
    await mcp.session_manager.start()

@app.on_event("shutdown") 
async def shutdown():
    await mcp.session_manager.stop()

# Run with: uvicorn app:app --host 0.0.0.0 --port 8000
```

### Shared services integration

```python
"""
FastAPI and MCP sharing database and services.
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from fastapi import FastAPI, Depends
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
import asyncpg

@dataclass
class SharedServices:
    """Shared services between FastAPI and MCP."""
    db_pool: asyncpg.Pool
    cache: dict = None

    def __post_init__(self):
        if self.cache is None:
            self.cache = {}

# Global services
services: SharedServices | None = None

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Shared lifespan for both FastAPI and MCP."""
    global services
    
    # Initialize shared services
    db_pool = await asyncpg.create_pool(
        "postgresql://user:pass@localhost/db",
        min_size=5,
        max_size=20
    )
    
    services = SharedServices(db_pool=db_pool)
    
    # Start MCP server
    await mcp.session_manager.start()
    
    try:
        yield
    finally:
        # Cleanup
        await mcp.session_manager.stop()
        await db_pool.close()

# Create FastAPI app with lifespan
app = FastAPI(lifespan=lifespan)

# MCP server with access to shared services
mcp = FastMCP("Shared Services MCP")

@mcp.tool()
async def query_database(
    sql: str, 
    ctx: Context[ServerSession, None]
) -> list[dict]:
    """Execute database query using shared connection pool."""
    if not services:
        raise RuntimeError("Services not initialized")
    
    await ctx.info(f"Executing query: {sql}")
    
    async with services.db_pool.acquire() as conn:
        rows = await conn.fetch(sql)
        results = [dict(row) for row in rows]
    
    await ctx.info(f"Query returned {len(results)} rows")
    return results

@mcp.tool()
async def cache_operation(
    key: str, 
    value: str | None = None,
    ctx: Context[ServerSession, None]
) -> dict:
    """Cache operations using shared cache."""
    if not services:
        raise RuntimeError("Services not initialized")
    
    if value is not None:
        # Set value
        services.cache[key] = value
        await ctx.info(f"Cached {key} = {value}")
        return {"action": "set", "key": key, "value": value}
    else:
        # Get value
        cached_value = services.cache.get(key)
        await ctx.debug(f"Retrieved {key} = {cached_value}")
        return {"action": "get", "key": key, "value": cached_value}

# FastAPI endpoints using shared services
def get_services() -> SharedServices:
    """Dependency to get shared services."""
    if not services:
        raise RuntimeError("Services not initialized")
    return services

@app.get("/api/users")
async def list_users(services: SharedServices = Depends(get_services)):
    """List users using shared database."""
    async with services.db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name FROM users LIMIT 10")
        return [{"id": row["id"], "name": row["name"]} for row in rows]

@app.get("/api/cache/{key}")
async def get_cache(key: str, services: SharedServices = Depends(get_services)):
    """Get cached value."""
    return {"key": key, "value": services.cache.get(key)}

# Mount MCP
app.mount("/mcp", mcp.streamable_http_app())
```

## Starlette integration

### Multiple MCP servers

```python
"""
Starlette app with multiple specialized MCP servers.
"""

import contextlib
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

# Create specialized MCP servers
user_mcp = FastMCP("User Management", stateless_http=True)
analytics_mcp = FastMCP("Analytics", stateless_http=True) 
admin_mcp = FastMCP("Admin Tools", stateless_http=True)

# User management tools
@user_mcp.tool()
def create_user(username: str, email: str) -> dict:
    """Create a new user."""
    user_id = f"user_{hash(username) % 10000:04d}"
    return {
        "user_id": user_id,
        "username": username,
        "email": email,
        "status": "created"
    }

@user_mcp.resource("user://{user_id}")
def get_user_profile(user_id: str) -> str:
    """Get user profile information."""
    return f"""User Profile: {user_id}
Name: Example User
Email: user@example.com
Status: Active
Created: 2024-01-01"""

# Analytics tools
@analytics_mcp.tool()
def calculate_metrics(data: list[float]) -> dict:
    """Calculate analytics metrics."""
    if not data:
        return {"error": "No data provided"}
    
    return {
        "count": len(data),
        "sum": sum(data),
        "mean": sum(data) / len(data),
        "min": min(data),
        "max": max(data)
    }

@analytics_mcp.resource("metrics://daily")
def get_daily_metrics() -> str:
    """Get daily metrics summary."""
    return """Daily Metrics Summary:
- Users: 1,234 active
- Requests: 45,678 total
- Errors: 12 (0.03%)
- Response time: 145ms avg"""

# Admin tools
@admin_mcp.tool()
def system_status() -> dict:
    """Get system status information."""
    return {
        "status": "healthy",
        "uptime": "5 days, 12 hours",
        "memory_usage": "45%",
        "cpu_usage": "23%",
        "disk_usage": "67%"
    }

# Regular Starlette routes
async def homepage(request):
    return JSONResponse({
        "message": "Multi-MCP Starlette Application",
        "mcp_services": {
            "users": "/users/mcp",
            "analytics": "/analytics/mcp", 
            "admin": "/admin/mcp"
        }
    })

async def health_check(request):
    return JSONResponse({"status": "healthy", "services": 3})

# Combined lifespan manager
@contextlib.asynccontextmanager
async def lifespan(app):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(user_mcp.session_manager.run())
        await stack.enter_async_context(analytics_mcp.session_manager.run())
        await stack.enter_async_context(admin_mcp.session_manager.run())
        yield

# Create Starlette application
app = Starlette(
    routes=[
        Route("/", homepage),
        Route("/health", health_check),
        Mount("/users", user_mcp.streamable_http_app()),
        Mount("/analytics", analytics_mcp.streamable_http_app()),
        Mount("/admin", admin_mcp.streamable_http_app()),
    ],
    lifespan=lifespan
)

# Run with: uvicorn app:app --host 0.0.0.0 --port 8000
```

## Django integration

### Django ASGI application

```python
"""
Django ASGI integration with MCP server.

Add to Django project's asgi.py file.
"""

import os
from django.core.asgi import get_asgi_application
from starlette.applications import Starlette
from starlette.routing import Mount
from mcp.server.fastmcp import FastMCP

# Configure Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')

# Get Django ASGI application
django_asgi_app = get_asgi_application()

# Create MCP server
mcp = FastMCP("Django MCP Integration")

@mcp.tool()
def django_model_stats() -> dict:
    """Get Django model statistics."""
    # Import Django models
    from django.contrib.auth.models import User
    from myapp.models import MyModel  # Your app models
    
    return {
        "users_count": User.objects.count(),
        "mymodel_count": MyModel.objects.count(),
        "recent_users": User.objects.filter(
            date_joined__gte=timezone.now() - timedelta(days=7)
        ).count()
    }

@mcp.resource("django://models/{model_name}")
def get_model_info(model_name: str) -> str:
    """Get information about Django models."""
    from django.apps import apps
    
    try:
        model = apps.get_model(model_name)
        field_info = []
        for field in model._meta.fields:
            field_info.append(f"- {field.name}: {field.__class__.__name__}")
        
        return f"""Model: {model_name}
Fields:
{chr(10).join(field_info)}
Table: {model._meta.db_table}"""
    
    except LookupError:
        return f"Model '{model_name}' not found"

# Combined ASGI application
async def startup():
    await mcp.session_manager.start()

async def shutdown():
    await mcp.session_manager.stop()

# Create combined application
from starlette.applications import Starlette

combined_app = Starlette()
combined_app.add_event_handler("startup", startup)
combined_app.add_event_handler("shutdown", shutdown)

combined_app.mount("/mcp", mcp.streamable_http_app())
combined_app.mount("/", django_asgi_app)

application = combined_app
```

### Django management command

```python
"""
Django management command to run MCP server.

Save as: myapp/management/commands/run_mcp.py
"""

from django.core.management.base import BaseCommand
from django.conf import settings
from mcp.server.fastmcp import FastMCP

class Command(BaseCommand):
    help = 'Run MCP server for Django integration'

    def add_arguments(self, parser):
        parser.add_argument('--host', default='localhost', help='Host to bind to')
        parser.add_argument('--port', type=int, default=8001, help='Port to bind to')
        parser.add_argument('--debug', action='store_true', help='Enable debug mode')

    def handle(self, *args, **options):
        from myapp.mcp_server import create_mcp_server
        
        mcp = create_mcp_server(debug=options['debug'])
        
        self.stdout.write(
            self.style.SUCCESS(
                f"Starting MCP server on {options['host']}:{options['port']}"
            )
        )
        
        mcp.run(
            transport="streamable-http",
            host=options['host'],
            port=options['port']
        )

# Usage: python manage.py run_mcp --host 0.0.0.0 --port 8001
```

## Middleware integration

### Shared authentication middleware

```python
"""
Shared authentication between FastAPI and MCP.
"""

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from mcp.server.fastmcp import FastMCP
import jwt

# Shared authentication logic
class AuthService:
    SECRET_KEY = "your-secret-key"
    
    @classmethod
    def verify_token(cls, token: str) -> dict | None:
        try:
            payload = jwt.decode(token, cls.SECRET_KEY, algorithms=["HS256"])
            return payload
        except jwt.InvalidTokenError:
            return None
    
    @classmethod
    def create_token(cls, user_id: str) -> str:
        return jwt.encode({"user_id": user_id}, cls.SECRET_KEY, algorithm="HS256")

# FastAPI security
security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    payload = AuthService.verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload

# Shared middleware
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip auth for certain paths
        if request.url.path in ["/health", "/login"]:
            return await call_next(request)
        
        # Check authorization header
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return Response("Unauthorized", status_code=401)
        
        token = auth_header.split(" ")[1]
        user = AuthService.verify_token(token)
        if not user:
            return Response("Invalid token", status_code=401)
        
        # Add user to request state
        request.state.user = user
        return await call_next(request)

# FastAPI app with auth
app = FastAPI()
app.add_middleware(AuthMiddleware)

@app.post("/login")
async def login(credentials: dict):
    # Simple login (use proper authentication in production)
    if credentials.get("username") == "admin" and credentials.get("password") == "secret":
        token = AuthService.create_token("admin")
        return {"access_token": token, "token_type": "bearer"}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/protected")
async def protected_endpoint(user: dict = Depends(get_current_user)):
    return {"message": f"Hello {user['user_id']}", "protected": True}

# MCP server (will inherit auth middleware when mounted)
mcp = FastMCP("Authenticated MCP")

@mcp.tool()
def authenticated_tool(data: str) -> str:
    """Tool that requires authentication."""
    # Authentication is handled by middleware
    return f"Processed: {data}"

# Mount MCP with auth middleware
app.mount("/mcp", mcp.streamable_http_app())

@app.on_event("startup")
async def startup():
    await mcp.session_manager.start()

@app.on_event("shutdown")
async def shutdown():
    await mcp.session_manager.stop()
```

## Load balancing and scaling

### Multi-instance deployment

```python
"""
Load-balanced MCP deployment with shared state.
"""

import redis.asyncio as redis
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
import os
import json

# Instance identification
INSTANCE_ID = os.getenv("INSTANCE_ID", "instance-1")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

app = FastAPI(title=f"MCP Instance {INSTANCE_ID}")

# Shared state via Redis
redis_client = redis.from_url(REDIS_URL)

mcp = FastMCP(f"MCP {INSTANCE_ID}", stateless_http=True)

@mcp.tool()
async def distributed_counter(operation: str = "increment") -> dict:
    """Distributed counter across instances."""
    key = "distributed_counter"
    
    if operation == "increment":
        new_value = await redis_client.incr(key)
        return {
            "operation": "increment",
            "value": new_value,
            "instance": INSTANCE_ID
        }
    elif operation == "get":
        value = await redis_client.get(key)
        return {
            "operation": "get", 
            "value": int(value) if value else 0,
            "instance": INSTANCE_ID
        }
    elif operation == "reset":
        await redis_client.delete(key)
        return {
            "operation": "reset",
            "value": 0,
            "instance": INSTANCE_ID
        }
    else:
        raise ValueError(f"Unknown operation: {operation}")

@mcp.tool()
async def instance_info() -> dict:
    """Get information about this instance."""
    return {
        "instance_id": INSTANCE_ID,
        "redis_connected": await redis_client.ping(),
        "status": "healthy"
    }

@mcp.resource("cluster://status")
async def cluster_status() -> str:
    """Get cluster status information."""
    # Store instance heartbeat
    await redis_client.setex(f"instance:{INSTANCE_ID}", 60, "alive")
    
    # Get all active instances
    keys = await redis_client.keys("instance:*")
    active_instances = [key.decode().split(":")[1] for key in keys]
    
    return f"""Cluster Status:
Active Instances: {len(active_instances)}
Instance List: {', '.join(active_instances)}
Current Instance: {INSTANCE_ID}
Redis Connected: True"""

# Health check endpoint
@app.get("/health")
async def health():
    return {
        "instance": INSTANCE_ID,
        "status": "healthy",
        "redis": await redis_client.ping()
    }

# Mount MCP
app.mount("/mcp", mcp.streamable_http_app())

@app.on_event("startup")
async def startup():
    await mcp.session_manager.start()
    # Register instance
    await redis_client.setex(f"instance:{INSTANCE_ID}", 60, "alive")

@app.on_event("shutdown")
async def shutdown():
    await mcp.session_manager.stop()
    # Unregister instance
    await redis_client.delete(f"instance:{INSTANCE_ID}")
    await redis_client.close()
```

## Testing ASGI integration

### Integration tests

```python
"""
Integration tests for ASGI-mounted MCP servers.
"""

import pytest
import asyncio
from httpx import AsyncClient
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

@pytest.fixture
async def test_app():
    """Create test FastAPI app with MCP integration."""
    app = FastAPI()
    mcp = FastMCP("Test MCP")
    
    @mcp.tool()
    def test_tool(value: str) -> str:
        return f"Test: {value}"
    
    @app.get("/api/test")
    async def api_test():
        return {"message": "API working"}
    
    app.mount("/mcp", mcp.streamable_http_app())
    
    @app.on_event("startup")
    async def startup():
        await mcp.session_manager.start()
    
    @app.on_event("shutdown")
    async def shutdown():
        await mcp.session_manager.stop()
    
    return app

@pytest.mark.asyncio
async def test_api_and_mcp_integration(test_app):
    """Test both API and MCP endpoints work."""
    async with AsyncClient(app=test_app, base_url="http://test") as client:
        # Test regular API endpoint
        api_response = await client.get("/api/test")
        assert api_response.status_code == 200
        assert api_response.json()["message"] == "API working"
        
        # Test MCP endpoint
        mcp_request = {
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "clientInfo": {"name": "Test", "version": "1.0.0"},
                "capabilities": {}
            }
        }
        
        mcp_response = await client.post("/mcp", json=mcp_request)
        assert mcp_response.status_code == 200
        
        # Test MCP tool call
        tool_request = {
            "method": "tools/call",
            "params": {
                "name": "test_tool",
                "arguments": {"value": "hello"}
            }
        }
        
        tool_response = await client.post("/mcp", json=tool_request)
        assert tool_response.status_code == 200
```

## Best practices

### Design guidelines

- **Separate concerns** - Keep web API and MCP functionality distinct
- **Share resources wisely** - Database pools, caches, but not request state
- **Use stateless MCP** - Better for scaling with web applications  
- **Consistent authentication** - Use same auth system for both interfaces
- **Health checks** - Monitor both web and MCP endpoints

### Performance considerations

- **Connection pooling** - Share database and Redis connections
- **Async operations** - Use async/await throughout
- **Resource limits** - Set appropriate timeouts and limits
- **Monitoring** - Track both web and MCP metrics
- **Load balancing** - Distribute load across instances

### Security best practices

- **Unified authentication** - Same security model for both interfaces
- **Input validation** - Validate data at both API and MCP layers
- **Rate limiting** - Apply limits to both endpoint types
- **HTTPS only** - Use TLS for all production traffic
- **Audit logging** - Log access to both interfaces

## Next steps

- **[Running servers](running-servers.md)** - Production deployment strategies
- **[Streamable HTTP](streamable-http.md)** - Advanced HTTP transport configuration
- **[Authentication](authentication.md)** - Secure your integrated applications
- **[Writing clients](writing-clients.md)** - Build clients for integrated services