# Context

The Context object provides tools and resources with access to request information, server capabilities, and communication channels. It's automatically injected into functions that request it.

## What is context?

Context gives your tools and resources access to:

- **Request metadata** - IDs, client information, progress tokens
- **Logging capabilities** - Send structured log messages to clients
- **Progress reporting** - Update clients on long-running operations
- **Resource reading** - Access other resources from within tools
- **User interaction** - Request additional input through elicitation
- **Server information** - Access to server configuration and state

## Basic context usage

### Getting context in functions

Add a parameter with the `Context` type annotation to any tool or resource:

```python
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("Context Example")

@mcp.tool()
async def my_tool(data: str, ctx: Context[ServerSession, None]) -> str:
    """Tool that uses context capabilities."""
    await ctx.info(f"Processing data: {data}")
    return f"Processed: {data}"

@mcp.resource("info://{type}")
async def get_info(type: str, ctx: Context) -> str:
    """Resource that logs access."""
    await ctx.debug(f"Accessed info resource: {type}")
    return f"Information about {type}"
```

### Context properties

```python
@mcp.tool()
async def context_info(ctx: Context) -> dict:
    """Get information from the context."""
    return {
        "request_id": ctx.request_id,
        "client_id": ctx.client_id,
        "server_name": ctx.fastmcp.name,
        "debug_mode": ctx.fastmcp.settings.debug
    }
```

## Logging and notifications

### Log levels

```python
@mcp.tool()
async def demonstrate_logging(message: str, ctx: Context) -> str:
    """Demonstrate different log levels."""
    # Debug information (usually filtered out in production)
    await ctx.debug(f"Debug: Starting to process '{message}'")
    
    # General information
    await ctx.info(f"Info: Processing message of length {len(message)}")
    
    # Warning about potential issues
    if len(message) > 100:
        await ctx.warning("Warning: Message is quite long, processing may take time")
    
    # Error conditions
    if not message.strip():
        await ctx.error("Error: Empty message provided")
        raise ValueError("Message cannot be empty")
    
    return f"Processed: {message}"

@mcp.tool()
async def custom_logging(level: str, message: str, ctx: Context) -> str:
    """Send log with custom level and logger name."""
    await ctx.log(
        level=level,
        message=message, 
        logger_name="custom.processor"
    )
    return f"Logged {level}: {message}"
```

### Structured logging

```python
@mcp.tool()
async def process_file(filename: str, ctx: Context) -> dict:
    """Process a file with structured logging."""
    await ctx.info(f"Starting file processing: {filename}")
    
    try:
        # Simulate file processing
        file_size = len(filename) * 100  # Mock size calculation
        
        await ctx.debug(f"File size calculated: {file_size} bytes")
        
        if file_size > 1000:
            await ctx.warning(f"Large file detected: {file_size} bytes")
        
        # Process file (simulated)
        processed_lines = file_size // 50
        await ctx.info(f"Processing complete: {processed_lines} lines processed")
        
        return {
            "filename": filename,
            "size": file_size,
            "lines_processed": processed_lines,
            "status": "success"
        }
        
    except Exception as e:
        await ctx.error(f"File processing failed: {e}")
        raise
```

## Progress reporting

### Basic progress updates

```python
import asyncio

@mcp.tool()
async def long_task(steps: int, ctx: Context) -> str:
    """Demonstrate progress reporting."""
    await ctx.info(f"Starting task with {steps} steps")
    
    for i in range(steps):
        # Simulate work
        await asyncio.sleep(0.1)
        
        # Report progress
        progress = (i + 1) / steps
        await ctx.report_progress(
            progress=progress,
            total=1.0,
            message=f"Completed step {i + 1} of {steps}"
        )
        
        await ctx.debug(f"Step {i + 1} completed")
    
    await ctx.info("Task completed successfully")
    return f"Finished all {steps} steps"
```

### Advanced progress tracking

```python
@mcp.tool()
async def multi_phase_task(
    phase_sizes: list[int], 
    ctx: Context
) -> dict[str, any]:
    """Task with multiple phases and detailed progress."""
    total_steps = sum(phase_sizes)
    completed_steps = 0
    
    await ctx.info(f"Starting multi-phase task: {len(phase_sizes)} phases, {total_steps} total steps")
    
    results = {}
    
    for phase_num, phase_size in enumerate(phase_sizes, 1):
        phase_name = f"Phase {phase_num}"
        await ctx.info(f"Starting {phase_name} ({phase_size} steps)")
        
        for step in range(phase_size):
            # Simulate work
            await asyncio.sleep(0.05)
            
            completed_steps += 1
            overall_progress = completed_steps / total_steps
            phase_progress = (step + 1) / phase_size
            
            await ctx.report_progress(
                progress=overall_progress,
                total=1.0,
                message=f"{phase_name}: Step {step + 1}/{phase_size} (Overall: {completed_steps}/{total_steps})"
            )
        
        results[phase_name] = f"Completed {phase_size} steps"
        await ctx.info(f"{phase_name} completed")
    
    return {
        "total_steps": total_steps,
        "phases_completed": len(phase_sizes),
        "results": results,
        "status": "success"
    }
```

## Resource reading

### Reading resources from tools

```python
@mcp.resource("config://{section}")
def get_config(section: str) -> str:
    """Get configuration for a section."""
    configs = {
        "database": "host=localhost port=5432 dbname=myapp",
        "cache": "redis://localhost:6379/0", 
        "logging": "level=INFO handler=file"
    }
    return configs.get(section, "Configuration not found")

@mcp.tool()
async def process_with_config(operation: str, ctx: Context) -> str:
    """Tool that reads configuration from resources."""
    try:
        # Read database configuration
        db_config = await ctx.read_resource("config://database")
        db_content = db_config.contents[0]
        
        if hasattr(db_content, 'text'):
            config_text = db_content.text
            await ctx.info(f"Using database config: {config_text}")
        
        # Read logging configuration  
        log_config = await ctx.read_resource("config://logging")
        log_content = log_config.contents[0]
        
        if hasattr(log_content, 'text'):
            log_text = log_content.text
            await ctx.debug(f"Logging config: {log_text}")
        
        # Perform operation with configuration
        return f"Operation '{operation}' completed with loaded configuration"
        
    except Exception as e:
        await ctx.error(f"Failed to read configuration: {e}")
        raise ValueError(f"Configuration error: {e}")

@mcp.tool()
async def analyze_resource(resource_uri: str, ctx: Context) -> dict:
    """Analyze content from any resource."""
    try:
        resource_content = await ctx.read_resource(resource_uri)
        
        analysis = {
            "uri": resource_uri,
            "content_blocks": len(resource_content.contents),
            "types": []
        }
        
        for content in resource_content.contents:
            if hasattr(content, 'text'):
                analysis["types"].append("text")
                word_count = len(content.text.split())
                analysis["word_count"] = word_count
                await ctx.info(f"Analyzed text resource: {word_count} words")
            elif hasattr(content, 'data'):
                analysis["types"].append("binary")
                data_size = len(content.data) if content.data else 0
                analysis["data_size"] = data_size
                await ctx.info(f"Analyzed binary resource: {data_size} bytes")
        
        return analysis
        
    except Exception as e:
        await ctx.error(f"Resource analysis failed: {e}")
        raise
```

## User interaction through elicitation

### Basic elicitation

```python
from pydantic import BaseModel, Field

class UserPreferences(BaseModel):
    """Schema for collecting user preferences."""
    theme: str = Field(description="Preferred theme (light/dark)")
    language: str = Field(description="Preferred language code")
    notifications: bool = Field(description="Enable notifications?")

@mcp.tool()
async def configure_settings(ctx: Context) -> dict:
    """Configure user settings through elicitation."""
    await ctx.info("Collecting user preferences...")
    
    result = await ctx.elicit(
        message="Please configure your preferences:",
        schema=UserPreferences
    )
    
    if result.action == "accept" and result.data:
        preferences = result.data
        await ctx.info(f"Settings configured: theme={preferences.theme}, language={preferences.language}")
        
        return {
            "status": "configured",
            "theme": preferences.theme,
            "language": preferences.language,
            "notifications": preferences.notifications
        }
    elif result.action == "decline":
        await ctx.info("User declined to configure settings")
        return {"status": "declined", "using_defaults": True}
    else:
        await ctx.warning("Settings configuration was cancelled")
        return {"status": "cancelled"}
```

### Advanced elicitation patterns

```python
class BookingRequest(BaseModel):
    """Schema for restaurant booking."""
    date: str = Field(description="Preferred date (YYYY-MM-DD)")
    time: str = Field(description="Preferred time (HH:MM)")
    party_size: int = Field(description="Number of people", ge=1, le=20)
    special_requests: str = Field(default="", description="Any special requests")

@mcp.tool()
async def book_restaurant(
    restaurant: str, 
    initial_date: str,
    ctx: Context
) -> dict:
    """Book restaurant with fallback options."""
    await ctx.info(f"Checking availability at {restaurant} for {initial_date}")
    
    # Simulate availability check
    if initial_date == "2024-12-25":  # Christmas - likely busy
        await ctx.warning(f"No availability on {initial_date}")
        
        result = await ctx.elicit(
            message=f"Sorry, {restaurant} is fully booked on {initial_date}. Would you like to try a different date?",
            schema=BookingRequest
        )
        
        if result.action == "accept" and result.data:
            booking = result.data
            await ctx.info(f"Alternative booking confirmed for {booking.date} at {booking.time}")
            
            return {
                "status": "booked",
                "restaurant": restaurant,
                "date": booking.date,
                "time": booking.time,
                "party_size": booking.party_size,
                "special_requests": booking.special_requests,
                "confirmation_id": f"BK{hash(booking.date + booking.time) % 10000:04d}"
            }
        else:
            return {"status": "cancelled", "reason": "No alternative date selected"}
    
    else:
        # Direct booking for available date
        return {
            "status": "booked",
            "restaurant": restaurant,
            "date": initial_date,
            "confirmation_id": f"BK{hash(initial_date) % 10000:04d}"
        }
```

## Server and session access

### Server information access

```python
@mcp.tool()
def server_status(ctx: Context) -> dict:
    """Get detailed server status information."""
    settings = ctx.fastmcp.settings
    
    return {
        "server": {
            "name": ctx.fastmcp.name,
            "instructions": ctx.fastmcp.instructions,
            "debug_mode": settings.debug,
            "log_level": settings.log_level
        },
        "network": {
            "host": settings.host,
            "port": settings.port,
            "mount_path": settings.mount_path,
            "sse_path": settings.sse_path
        },
        "features": {
            "stateless_http": settings.stateless_http,
            "json_response": getattr(settings, 'json_response', False)
        }
    }
```

### Session information

```python
@mcp.tool()
def session_info(ctx: Context) -> dict:
    """Get information about the current session."""
    session = ctx.session
    
    info = {
        "request_id": ctx.request_id,
        "client_id": ctx.client_id
    }
    
    # Access client capabilities if available
    if hasattr(session, 'client_params'):
        client_params = session.client_params
        info["client_capabilities"] = {
            "name": getattr(client_params, 'clientInfo', {}).get('name', 'Unknown'),
            "version": getattr(client_params, 'clientInfo', {}).get('version', 'Unknown')
        }
    
    return info
```

## Lifespan context access

### Accessing lifespan resources

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

class DatabaseConnection:
    """Mock database connection."""
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.is_connected = False
    
    async def connect(self):
        self.is_connected = True
        return self
    
    async def disconnect(self):
        self.is_connected = False
    
    async def query(self, sql: str) -> list[dict]:
        if not self.is_connected:
            raise RuntimeError("Database not connected")
        return [{"id": 1, "name": "test", "sql": sql}]

@dataclass
class AppContext:
    """Application context with shared resources."""
    db: DatabaseConnection
    api_key: str
    cache_enabled: bool

@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle."""
    # Startup
    db = DatabaseConnection("postgresql://localhost/myapp")
    await db.connect()
    
    context = AppContext(
        db=db,
        api_key="secret-api-key-123",
        cache_enabled=True
    )
    
    try:
        yield context
    finally:
        # Shutdown
        await db.disconnect()

mcp = FastMCP("Database App", lifespan=app_lifespan)

@mcp.tool()
async def query_data(
    sql: str, 
    ctx: Context[ServerSession, AppContext]
) -> dict:
    """Query database using lifespan context."""
    # Access lifespan context
    app_ctx = ctx.request_context.lifespan_context
    
    await ctx.info(f"Executing query with API key: {app_ctx.api_key[:10]}...")
    
    if app_ctx.cache_enabled:
        await ctx.debug("Cache is enabled for this query")
    
    # Use database connection from lifespan
    results = await app_ctx.db.query(sql)
    
    await ctx.info(f"Query returned {len(results)} rows")
    
    return {
        "sql": sql,
        "results": results,
        "cached": app_ctx.cache_enabled,
        "connection_status": app_ctx.db.is_connected
    }
```

## Advanced context patterns

### Context middleware pattern

```python
from functools import wraps

def with_timing(func):
    """Decorator to add timing information to context operations."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Find context in arguments
        ctx = None
        for arg in args:
            if isinstance(arg, Context):
                ctx = arg
                break
        
        if ctx:
            import time
            start_time = time.time()
            await ctx.debug(f"Starting {func.__name__}")
            
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                await ctx.info(f"Completed {func.__name__} in {duration:.2f}s")
                return result
            except Exception as e:
                duration = time.time() - start_time
                await ctx.error(f"Failed {func.__name__} after {duration:.2f}s: {e}")
                raise
        else:
            return await func(*args, **kwargs)
    
    return wrapper

@mcp.tool()
@with_timing
async def timed_operation(data: str, ctx: Context) -> str:
    """Operation with automatic timing."""
    await asyncio.sleep(0.5)  # Simulate work
    return f"Processed: {data}"
```

### Context validation

```python
def require_debug_mode(func):
    """Decorator to require debug mode for certain operations."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        ctx = None
        for arg in args:
            if isinstance(arg, Context):
                ctx = arg
                break
        
        if ctx and not ctx.fastmcp.settings.debug:
            await ctx.error("Debug mode required for this operation")
            raise ValueError("Debug mode required")
        
        return await func(*args, **kwargs)
    
    return wrapper

@mcp.tool()
@require_debug_mode
async def debug_operation(ctx: Context) -> dict:
    """Operation that requires debug mode."""
    await ctx.info("Performing debug operation")
    return {"debug_info": "sensitive debug data"}
```

## Testing context functionality

### Mocking context for testing

```python
import pytest
from unittest.mock import AsyncMock, Mock

@pytest.mark.asyncio
async def test_tool_with_context():
    # Create mock context
    mock_ctx = Mock()
    mock_ctx.info = AsyncMock()
    mock_ctx.debug = AsyncMock()
    mock_ctx.request_id = "test-123"
    
    # Test the tool function
    @mcp.tool()
    async def test_tool(data: str, ctx: Context) -> str:
        await ctx.info(f"Processing: {data}")
        return f"Result: {data}"
    
    result = await test_tool("test data", mock_ctx)
    
    assert result == "Result: test data"
    mock_ctx.info.assert_called_once_with("Processing: test data")

@pytest.mark.asyncio  
async def test_progress_reporting():
    mock_ctx = Mock()
    mock_ctx.report_progress = AsyncMock()
    mock_ctx.info = AsyncMock()
    
    @mcp.tool()
    async def progress_tool(steps: int, ctx: Context) -> str:
        for i in range(steps):
            await ctx.report_progress(
                progress=(i + 1) / steps,
                total=1.0,
                message=f"Step {i + 1}"
            )
        return "Complete"
    
    result = await progress_tool(3, mock_ctx)
    
    assert result == "Complete"
    assert mock_ctx.report_progress.call_count == 3
```

## Best practices

### Context usage guidelines

- **Check context availability** - Not all functions need context
- **Use appropriate log levels** - Debug for detailed info, info for general updates
- **Handle context errors gracefully** - Don't assume context operations always succeed
- **Minimize context overhead** - Don't over-log or spam progress updates

### Performance considerations

- **Async context operations** - All context methods are async, use await
- **Batch logging** - Group related log messages when possible
- **Progress update frequency** - Update progress reasonably, not on every tiny step
- **Resource reading caching** - Cache frequently accessed resource content

### Security considerations

- **Sensitive data in logs** - Never log passwords, tokens, or personal data
- **Context information exposure** - Be careful what server info you expose
- **Elicitation data validation** - Always validate data from user elicitation
- **Resource access control** - Validate resource URIs in read_resource calls

## Next steps

- **[Server lifecycle](servers.md)** - Understanding server startup and shutdown
- **[Advanced tools](tools.md)** - Building complex tools with context
- **[Progress patterns](progress-logging.md)** - Advanced progress reporting techniques
- **[Authentication context](authentication.md)** - Using context with authenticated requests