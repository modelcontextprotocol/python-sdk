# Servers

Learn how to create and manage MCP servers, including lifecycle management, configuration, and advanced patterns.

## What is an MCP server?

An MCP server exposes functionality to LLM applications through three core primitives:

- **Resources** - Data that can be read by LLMs
- **Tools** - Functions that LLMs can call  
- **Prompts** - Templates for LLM interactions

The FastMCP framework provides a high-level, decorator-based way to build servers quickly.

## Basic server creation

### Minimal server

```python
from mcp.server.fastmcp import FastMCP

# Create a server
mcp = FastMCP("My Server")

@mcp.tool()
def hello(name: str = "World") -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"

if __name__ == "__main__":
    mcp.run()
```

### Server with configuration

```python
from mcp.server.fastmcp import FastMCP

# Create server with custom configuration
mcp = FastMCP(
    name="Analytics Server",
    instructions="Provides data analytics and reporting tools"
)

@mcp.tool()
def analyze_data(data: list[int]) -> dict[str, float]:
    """Analyze a list of numbers."""
    return {
        "mean": sum(data) / len(data),
        "max": max(data),
        "min": min(data),
        "count": len(data)
    }
```

## Server lifecycle management

### Using lifespan for startup/shutdown

For servers that need to initialize resources (databases, connections, etc.), use the lifespan pattern:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession


# Mock database for example
class Database:
    @classmethod
    async def connect(cls) -> "Database":
        print("Connecting to database...")
        return cls()
    
    async def disconnect(self) -> None:
        print("Disconnecting from database...")
    
    def query(self, sql: str) -> dict:
        return {"result": f"Query result for: {sql}"}


@dataclass
class AppContext:
    """Application context with typed dependencies."""
    db: Database


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle with type-safe context."""
    # Startup: initialize resources
    db = await Database.connect()
    try:
        yield AppContext(db=db)
    finally:
        # Shutdown: cleanup resources
        await db.disconnect()


# Create server with lifespan
mcp = FastMCP("Database Server", lifespan=app_lifespan)


@mcp.tool()
def query_database(sql: str, ctx: Context[ServerSession, AppContext]) -> dict:
    """Execute a database query."""
    # Access the database from lifespan context
    db = ctx.request_context.lifespan_context.db
    return db.query(sql)
```

### Benefits of lifespan management

- **Resource initialization** - Set up databases, API clients, configuration
- **Graceful shutdown** - Clean up resources when server stops
- **Type safety** - Access initialized resources with full type hints
- **Shared state** - Resources available to all request handlers

## Server configuration

### Development vs production settings

```python
from mcp.server.fastmcp import FastMCP

# Development server with debug features
dev_mcp = FastMCP(
    "Dev Server",
    debug=True,
    log_level="DEBUG"
)

# Production server with optimized settings
prod_mcp = FastMCP(
    "Production Server", 
    debug=False,
    log_level="INFO",
    stateless_http=True  # Better for scaling
)
```

### Transport configuration

```python
# Configure for different transports
mcp = FastMCP(
    "Multi-Transport Server",
    host="0.0.0.0",  # Accept connections from any host
    port=8000,
    mount_path="/api/mcp",  # Custom path for HTTP transport
    sse_path="/events",     # Custom SSE endpoint
)

# Run with specific transport
if __name__ == "__main__":
    mcp.run(transport="streamable-http")  # or "stdio", "sse"
```

## Error handling and validation

### Input validation

```python
from typing import Annotated
from pydantic import Field, validator

@mcp.tool()
def process_age(
    age: Annotated[int, Field(ge=0, le=150, description="Person's age")]
) -> str:
    """Process a person's age with validation."""
    if age < 18:
        return "Minor"
    elif age < 65:
        return "Adult"
    else:
        return "Senior"
```

### Error handling patterns

```python
@mcp.tool()
def divide_numbers(a: float, b: float) -> float:
    """Divide two numbers with error handling."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b

@mcp.tool()
async def fetch_data(url: str, ctx: Context) -> str:
    """Fetch data with proper error handling."""
    try:
        # Simulate network request
        if not url.startswith("http"):
            raise ValueError("URL must start with http or https")
        
        await ctx.info(f"Fetching data from {url}")
        # ... actual implementation
        return "Data fetched successfully"
        
    except ValueError as e:
        await ctx.error(f"Invalid URL: {e}")
        raise
    except Exception as e:
        await ctx.error(f"Failed to fetch data: {e}")
        raise
```

## Server capabilities and metadata

### Declaring capabilities

```python
# Server automatically declares capabilities based on registered handlers
mcp = FastMCP("Feature Server")

# Adding tools automatically enables the 'tools' capability
@mcp.tool()
def my_tool() -> str:
    return "Tool result"

# Adding resources automatically enables the 'resources' capability  
@mcp.resource("data://{id}")
def get_data(id: str) -> str:
    return f"Data for {id}"

# Adding prompts automatically enables the 'prompts' capability
@mcp.prompt()
def my_prompt() -> str:
    return "Prompt template"
```

### Server metadata access

```python
@mcp.tool()
def server_info(ctx: Context) -> dict:
    """Get information about the current server."""
    return {
        "name": ctx.fastmcp.name,
        "instructions": ctx.fastmcp.instructions,
        "debug_mode": ctx.fastmcp.settings.debug,
        "host": ctx.fastmcp.settings.host,
        "port": ctx.fastmcp.settings.port,
    }
```

## Testing servers

### Unit testing individual components

```python
import pytest
from mcp.server.fastmcp import FastMCP

def test_server_creation():
    mcp = FastMCP("Test Server")
    assert mcp.name == "Test Server"

@pytest.mark.asyncio
async def test_tool_functionality():
    mcp = FastMCP("Test")
    
    @mcp.tool()
    def add(a: int, b: int) -> int:
        return a + b
    
    # Test the underlying function
    result = add(2, 3)
    assert result == 5
```

### Integration testing with MCP Inspector

```bash
# Start server in test mode
uv run mcp dev server.py --port 8001

# Test with curl
curl -X POST http://localhost:8001/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/list", "params": {}}'
```

## Common patterns

### Environment-based configuration

```python
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "Configurable Server",
    debug=os.getenv("DEBUG", "false").lower() == "true",
    host=os.getenv("HOST", "localhost"),
    port=int(os.getenv("PORT", "8000"))
)
```

### Multi-server applications

```python
# Create specialized servers for different domains
auth_server = FastMCP("Auth Server")
data_server = FastMCP("Data Server")

@auth_server.tool()
def login(username: str, password: str) -> str:
    """Handle user authentication."""
    # ... auth logic
    return "Login successful"

@data_server.tool() 
def get_user_data(user_id: str) -> dict:
    """Retrieve user data."""
    # ... data retrieval logic
    return {"user_id": user_id, "name": "John Doe"}
```

## Best practices

### Server design

- **Single responsibility** - Each server should have a focused purpose
- **Stateless when possible** - Avoid server-side state for better scalability  
- **Clear naming** - Use descriptive server and tool names
- **Documentation** - Provide clear docstrings for all public interfaces

### Performance considerations

- **Use async/await** - For I/O-bound operations
- **Connection pooling** - Reuse database connections via lifespan
- **Caching** - Cache expensive computations where appropriate
- **Batch operations** - Group related operations when possible

### Security

- **Input validation** - Validate all tool parameters
- **Error handling** - Don't expose sensitive information in errors
- **Authentication** - Use OAuth 2.1 for protected resources
- **Rate limiting** - Implement rate limiting for expensive operations

## Next steps

- **[Learn about tools](tools.md)** - Create powerful LLM-callable functions
- **[Working with resources](resources.md)** - Expose data effectively
- **[Server deployment](running-servers.md)** - Run servers in production
- **[Authentication](authentication.md)** - Secure your servers