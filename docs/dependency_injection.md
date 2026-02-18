# Dependency Injection

MCPServer supports FastAPI-style dependency injection for tools, prompts, and resources.

## Overview

The dependency injection (DI) system allows you to declare dependencies for your tools, prompts, and resources using the `Depends()` marker. Dependencies are automatically resolved and injected when the function is called.

## Basic Usage

### Simple Dependency

```python
from mcp import MCPServer, Depends

def get_database():
    """Dependency provider for database."""
    return Database()

server = MCPServer("my-server")

@server.tool()
def query_users(
    limit: int,
    db: Database = Depends(get_database),
) -> list[User]:
    """Query users from database."""
    return db.query("SELECT * FROM users LIMIT ?", limit)
```

### Nested Dependencies

Dependencies can depend on other dependencies:

```python
def get_config() -> Config:
    """Get configuration."""
    return Config(db_url="postgresql://localhost/mydb")

def get_database(config: Config = Depends(get_config)) -> Database:
    """Get database instance with config."""
    return Database(config.db_url)

def get_repository(db: Database = Depends(get_database)) -> UserRepository:
    """Get user repository with database."""
    return UserRepository(db)

@server.tool()
def find_user(
    user_id: int,
    repo: UserRepository = Depends(get_repository),
) -> User:
    """Find user by ID."""
    return repo.find(user_id)
```

### Async Dependencies

Both sync and async dependency functions are supported:

```python
async def get_async_database() -> Database:
    """Async dependency provider."""
    return await Database.connect()

@server.tool()
async def query_with_async(
    db: Database = Depends(get_async_database),
) -> list[User]:
    """Query users using async database."""
    return await db.query("SELECT * FROM users")
```

### Multiple Dependencies

Tools can use multiple dependencies:

```python
@server.tool()
def combine(
    prefix: str = Depends(get_prefix),
    suffix: str = Depends(get_suffix),
) -> str:
    """Combine multiple dependencies."""
    return f"{prefix}:{suffix}"
```

## Testing

### Override Dependencies

The `override_dependency()` method allows you to replace dependencies with test implementations:

```python
def get_db() -> Database:
    """Production database."""
    return Database()

def get_test_db() -> Database:
    """Test database."""
    return MockDatabase([...])

server = MCPServer("test-server")

@server.tool()
def show_user(user_id: int, db: Database = Depends(get_db)) -> User:
    """Show user from database."""
    return db.find(user_id)

# In tests
server.override_dependency(get_db, get_test_db)
# Now show_user will use get_test_db instead of get_db
```

## Caching

### Per-Request Caching

By default, dependencies are cached per request. If the same dependency is used multiple times in a single request, it will only be resolved once:

```python
call_count = 0

def get_cached_value() -> str:
    """Cached dependency."""
    global call_count
    call_count += 1
    return "cached"

@server.tool()
def use_twice(
    first: str = Depends(get_cached_value),
    second: str = Depends(get_cached_value),
) -> str:
    """Both first and second get the same cached instance."""
    return f"{first}:{second}"

# After calling use_twice, call_count will be 1, not 2
```

### Disable Caching

To disable caching and get a fresh instance each time:

```python
def get_fresh_value() -> str:
    """Non-cached dependency."""
    return str(uuid.uuid4())

@server.tool()
def use_fresh(
    value: str = Depends(get_fresh_value, use_cache=False),
) -> str:
    """Each call gets a fresh value."""
    return value
```

## Integration with Context

Dependencies work alongside the existing Context parameter injection:

```python
from mcp.server.mcpserver.server import Context

@server.tool()
def tool_with_both(
    arg: int,
    ctx: Context,
    db: Database = Depends(get_database),
) -> str:
    """Tool using both context and dependency."""
    ctx.info(f"Querying with arg={arg}")
    return db.query(arg)
```

## Limitations

### Current Limitations

1. **Prompts and Resources**: Dependency injection is currently only fully supported for tools. Prompt and resource support is planned for a future release.

2. **Scope**: Only request-scoped dependencies are currently supported. Session and server-scoped dependencies may be added in the future.

3. **Circular Dependencies**: Circular dependencies are not detected and will cause a runtime error.

## Best Practices

### 1. Use Type Hints

Always provide type hints for your dependency functions:

```python
def get_db() -> Database:  # Type hint helps with IDE support
    return Database()
```

### 2. Keep Dependencies Focused

Each dependency should have a single responsibility:

```python
# Good
def get_db_connection() -> Connection:
    return Connection()

def get_user_repo(conn: Connection = Depends(get_db_connection)) -> UserRepository:
    return UserRepository(conn)

# Avoid
def get_everything() -> tuple[Connection, UserRepository, Cache]:
    return ...
```

### 3. Use Descriptive Names

Name your dependency functions clearly:

```python
# Good
def get_postgresql_connection() -> Connection:
    return PostgreSQLConnection()

# Avoid
def get_conn() -> Connection:
    return ...
```

### 4. Document Dependencies

Add docstrings to your dependency functions:

```python
def get_database() -> Database:
    """Get the PostgreSQL database connection.

    The connection is created at startup and reused across requests.
    """
    return Database()
```

## Migration Guide

### From Global Variables

**Before:**
```python
# Global state
DB = Database()

@server.tool()
def query_users(limit: int) -> list[User]:
    return DB.query("SELECT * FROM users LIMIT ?", limit)
```

**After:**
```python
# Dependency injection
def get_db() -> Database:
    return Database()

@server.tool()
def query_users(limit: int, db: Database = Depends(get_db)) -> list[User]:
    return db.query("SELECT * FROM users LIMIT ?", limit)
```

### From Context State

**Before:**
```python
@server.tool()
def query_users(limit: int, ctx: Context) -> list[User]:
    db = ctx.lifespan_context.db
    return db.query("SELECT * FROM users LIMIT ?", limit)
```

**After:**
```python
def get_db(ctx: Context) -> Database:
    # Can still access context if needed
    return ctx.lifespan_context.db

@server.tool()
def query_users(limit: int, db: Database = Depends(get_db)) -> list[User]:
    return db.query("SELECT * FROM users LIMIT ?", limit)
```

## Examples

### Complete Example

```python
from mcp import MCPServer, Depends

# 1. Define dependencies
def get_config() -> Config:
    """Get application configuration."""
    return Config(
        db_url="postgresql://localhost/mydb",
        api_key="secret",
    )

def get_database(config: Config = Depends(get_config)) -> Database:
    """Get database connection."""
    return Database(config.db_url)

def get_user_service(db: Database = Depends(get_database)) -> UserService:
    """Get user service."""
    return UserService(db)

# 2. Create server
server = MCPServer("my-app")

# 3. Use dependencies in tools
@server.tool()
def get_user(
    user_id: int,
    service: UserService = Depends(get_user_service),
) -> User:
    """Get user by ID."""
    return service.get_user(user_id)

@server.tool()
def list_users(
    limit: int,
    service: UserService = Depends(get_user_service),
) -> list[User]:
    """List users."""
    return service.list_users(limit=limit)
```

### Testing Example

```python
import pytest
from mcp import MCPServer, Depends
from mcp.client import Client

# Production code
def get_db() -> Database:
    return PostgreSQLDatabase()

@server.tool()
def get_user(user_id: int, db: Database = Depends(get_db)) -> User:
    return db.find(user_id)

# Test code
def get_test_db() -> Database:
    return MockDatabase([
        User(id=1, name="Alice"),
        User(id=2, name="Bob"),
    ])

@pytest.mark.anyio
async def test_get_user():
    server = MCPServer("test-server")

    @server.tool()
    def get_user(user_id: int, db: Database = Depends(get_db)) -> User:
        return db.find(user_id)

    # Override the dependency
    server.override_dependency(get_db, get_test_db)

    async with Client(server) as client:
        result = await client.call_tool("get_user", {"user_id": 1})
        assert result.structured_content == {"id": 1, "name": "Alice"}
```

## Advanced Topics

### Dependency Factories

You can create factory functions for dependencies:

```python
def get_repository(table: str):
    """Factory for creating repositories."""
    def _get_repo(db: Database = Depends(get_database)) -> BaseRepository:
        if table == "users":
            return UserRepository(db)
        elif table == "posts":
            return PostRepository(db)
        else:
            raise ValueError(f"Unknown table: {table}")
    return _get_repo

@server.tool()
def get_users(repo: BaseRepository = Depends(get_repository("users"))) -> list[User]:
    return repo.all()
```

### Context-Aware Dependencies

Dependencies can access the Context if needed:

```python
def get_request_id(ctx: Context) -> str:
    """Get the current request ID."""
    return ctx.request_id

@server.tool()
def log_action(
    action: str,
    request_id: str = Depends(get_request_id),
) -> str:
    return f"Action {action} in request {request_id}"
```

## API Reference

### Depends

```python
class Depends(Generic[T]):
    """Marker class for dependency injection.

    Args:
        dependency: A callable that provides the dependency
        use_cache: Whether to cache the dependency result (default: True)
    """
```

### MCPServer.override_dependency

```python
def override_dependency(
    self,
    original: Callable[..., Any],
    override: Callable[..., Any],
) -> None:
    """Override a dependency for testing.

    Args:
        original: The original dependency function to override
        override: The override function to use instead
    """
```

## Troubleshooting

### Dependencies Not Being Injected

If your dependencies are not being injected, make sure:

1. The dependency function is defined with the correct signature
2. The `Depends()` marker is used as a default value
3. Type hints are provided for both the dependency and parameter

```python
# Correct
def get_db() -> Database:
    return Database()

@server.tool()
def my_tool(db: Database = Depends(get_db)) -> str:
    return db.query()

# Incorrect - missing type hint
@server.tool()
def my_tool(db = Depends(get_db)) -> str:  # Missing type hint
    return db.query()
```

### Override Not Working

If `override_dependency()` doesn't seem to work, make sure you're overriding the exact same function object:

```python
# Correct
def get_db() -> Database:
    return Database()

server.override_dependency(get_db, get_test_db)  # Same function

# Incorrect - won't work
def get_db() -> Database:
    return Database()

def get_db_2() -> Database:
    return get_db()

server.override_dependency(get_db_2, get_test_db)  # Different function!
```

### Circular Dependencies

If you have circular dependencies, you'll get a `RecursionError`. Refactor your code to break the cycle:

```python
# Circular - will fail
def get_a(b: B = Depends(get_b)) -> A:
    return A(b)

def get_b(a: A = Depends(get_a)) -> B:
    return B(a)

# Fixed - break the cycle
def get_a() -> A:
    return A()

def get_b(a: A = Depends(get_a)) -> B:
    return B(a)
```
