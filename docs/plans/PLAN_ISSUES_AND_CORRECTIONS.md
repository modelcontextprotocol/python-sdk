# Plan Issues and Corrections

## Critical Issues Found

### Issue 1: Server Lifespan Integration Location is WRONG ⚠️

**Current Plan (Task 1.3):**
- Suggests running server lifespan in `StreamableHTTPSessionManager.run()` method
- Modifies `session_manager.run()` to wrap server lifespan around task group

**Problem:**
Looking at the actual code flow:
1. `Server.streamable_http_app()` (line 524-634) creates a Starlette app
2. At line 633, it sets: `lifespan=lambda app: session_manager.run()`
3. `StreamableHTTPSessionManager.run()` creates a task group for sessions
4. Each session calls `self.app.run()` (lines 170, 238) which enters the session lifespan

**Correct Approach:**
The server lifespan should run in the **Starlette app's lifespan**, NOT in `session_manager.run()`.

The lambda at line 633 should be replaced with:
```python
# OLD (line 633):
lifespan=lambda app: session_manager.run(),

# NEW:
lifespan=create_app_lifespan(session_manager, server_lifespan_manager),
```

Where `create_app_lifespan` is a function that:
1. Runs server lifespan (once at app startup)
2. Then runs `session_manager.run()`

### Issue 2: StreamableHTTPSessionManager Doesn't Need server_lifespan_manager

**Current Plan (Task 1.3, Step 2):**
```python
def __init__(
    self,
    ...
    server_lifespan_manager: ServerLifespanManager[Any] | None = None,
):
```

**Problem:**
The `StreamableHTTPSessionManager` should NOT receive a `server_lifespan_manager` parameter. The server lifespan runs at the **Starlette app level**, not the session manager level.

The session manager only needs to:
1. Create task groups for sessions
2. Handle HTTP requests
3. Manage session lifecycle

### Issue 3: Context Variable Naming Conflict

**Current Plan:**
```python
server_lifespan_ctx: contextvars.ContextVar[ServerLifespanContextT] = contextvars.ContextVar(
    "server_lifespan_ctx",
    default=None,
)
```

**Problem:**
There's already a `request_ctx` context variable at line 77 of `server.py`. The naming should be consistent.

**Correction:**
```python
# Use consistent naming pattern
server_lifespan_context_var: contextvars.ContextVar[ServerLifespanContextT] = ...
```

### Issue 4: Missing Import Statement

**Current Plan:**
Doesn't address the import at line 88 of `server.py`:
```python
@asynccontextmanager
async def lifespan(_: Server[LifespanResultT]) -> AsyncIterator[dict[str, Any]]:
```

**Problem:**
After replacing `lifespan` parameter with `session_lifespan`, this function should be renamed to `session_lifespan`.

**Correction:**
```python
# OLD:
@asynccontextmanager
async def lifespan(_: Server[LifespanResultT]) -> AsyncIterator[dict[str, Any]]:
    """Default lifespan context manager that does nothing."""
    yield {}

# NEW:
@asynccontextmanager
async def session_lifespan(_: Server[LifespanResultT]) -> AsyncIterator[dict[str, Any]]:
    """Default session lifespan context manager that does nothing."""
    yield {}
```

And update the default value in `__init__`:
```python
session_lifespan: Callable[...] = session_lifespan,  # not 'lifespan'
```

### Issue 5: Type Variable for Server Lifespan

**Current Plan:**
Uses `Any` for server lifespan context type.

**Problem:**
Should use a proper type variable for type safety.

**Correction:**
Add a new type variable in `server.py`:
```python
# Around line 75:
LifespanResultT = TypeVar("LifespanResultT", default=Any)
ServerLifespanContextT = TypeVar("ServerLifespanContextT", default=Any)

# Update Server class declaration:
class Server(Generic[ServerLifespanContextT, LifespanResultT]):
```

### Issue 6: Task 1.4 is Incomplete

**Current Plan (Task 1.4):**
Shows creating `ServerLifespanManager` in `streamable_http_app()` and passing it to `StreamableHTTPSessionManager`.

**Problem:**
This is wrong based on Issue 1 and 2. The `ServerLifespanManager` should be used in the Starlette app lifespan, not passed to session manager.

**Correction:**
In `Server.streamable_http_app()` method:

```python
def streamable_http_app(self, ...) -> Starlette:
    # ... existing code ...

    # Create server lifespan manager if server_lifespan is configured
    server_lifespan_manager = None
    if self.server_lifespan is not None:
        server_lifespan_manager = ServerLifespanManager(server_lifespan=self.server_lifespan)

    session_manager = StreamableHTTPSessionManager(
        app=self,
        # ... other params ...
        # NOTE: NOT passing server_lifespan_manager here!
    )

    # Create the app with proper lifespan
    return Starlette(
        debug=debug,
        routes=routes,
        middleware=middleware,
        lifespan=create_app_lifespan(session_manager, server_lifespan_manager),
    )
```

And add helper function:
```python
@contextlib.asynccontextmanager
async def create_app_lifespan(
    session_manager: StreamableHTTPSessionManager,
    server_lifespan_manager: ServerLifespanManager[Any] | None,
) -> AsyncIterator[None]:
    """Combined lifespan for Starlette app.

    Runs server lifespan first (if configured), then session manager.
    """
    if server_lifespan_manager:
        async with server_lifespan_manager.run(session_manager.app):
            async with session_manager.run():
                yield
    else:
        async with session_manager.run():
            yield
```

### Issue 7: Handler Context Access Uses Wrong Context Variable Name

**Current Plan (Task 2.2):**
```python
from mcp.server.server_lifespan import server_lifespan_ctx
try:
    server_lifespan_context = server_lifespan_ctx.get()
```

**Problem:**
If we rename to `server_lifespan_context_var` (Issue 3), this needs to be updated.

**Correction:**
```python
from mcp.server.server_lifespan import server_lifespan_context_var
try:
    server_lifespan_context = server_lifespan_context_var.get()
except LookupError:
    server_lifespan_context = {}
```

## Summary of Required Changes

1. **Task 1.2**: Rename `server_lifespan_ctx` to `server_lifespan_context_var`
2. **Task 1.3**: Delete entire task - server lifespan should NOT go in `StreamableHTTPSessionManager`
3. **Task 1.4**: Complete rewrite - server lifespan goes in Starlette app lifespan, not session manager
4. **Task 2.1**: Add new type variable `ServerLifespanContextT`
5. **Task 2.2**: Update import from `server_lifespan_ctx` to `server_lifespan_context_var`
6. **Add Task 1.5**: Rename `lifespan` function to `session_lifespan` (line 88 of server.py)

## Corrected Architecture

```
Starlette App Startup
├── Server Lifespan (runs ONCE)
│   ├── Initialize database pools
│   ├── Load ML models
│   └── Store in server_lifespan_context_var
├── Session Manager starts
│   └── Task Group for sessions
└── For Each Client Connection:
    └── Session Lifespan (runs PER-CLIENT)
        ├── Initialize session-specific resources
        └── Handler can access both:
            ├── server_lifespan_context (shared)
            └── session_lifespan_context (per-client)
```

## Files That Actually Need Modification

1. `src/mcp/server/lowlevel/server.py`:
   - Add `server_lifespan` parameter
   - Replace `lifespan` with `session_lifespan`
   - Rename `lifespan()` function to `session_lifespan()`
   - Update `streamable_http_app()` to use new lifespan structure

2. `src/mcp/server/server_lifespan.py` (NEW):
   - Create with corrected context variable name

3. `src/mcp/server/context.py`:
   - Update `ServerRequestContext` to have two context fields

4. `tests/server/test_lifespan.py`:
   - Update to use new API

5. `docs/migration.md`:
   - Document breaking change
