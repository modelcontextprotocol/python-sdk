# Low-Level Server Refactoring Plan

## Overview

This document outlines the plan to refactor the low-level `Server` class (`src/mcp/server/lowlevel/server.py`) from a **decorator-based approach** to a **constructor-based callback approach**.

### Current Approach (Decorator-Based)

```python
server = Server("my-server")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [...]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> dict:
    return {"result": "..."}
```

### Proposed Approach (Constructor-Based)

All handlers receive **context as the first parameter** and **params as the second parameter**, and return a properly typed result object.

```python
async def handle_list_tools(
    ctx: RequestContext[ServerSession, Any, Any],
    params: types.PaginatedRequestParams | None,
) -> types.ListToolsResult:
    return types.ListToolsResult(tools=[...])

async def handle_call_tool(
    ctx: RequestContext[ServerSession, Any, Any],
    params: types.CallToolRequestParams,
) -> types.CallToolResult:
    return types.CallToolResult(content=[...])

server = Server(
    name="my-server",
    on_list_tools=handle_list_tools,
    on_call_tool=handle_call_tool,
)
```

---

## Phase 1: Update Constructor Signature

**File:** `src/mcp/server/lowlevel/server.py`

Add new handler parameters with **inline types** (no type aliases). Each handler follows the pattern:
- First parameter: `RequestContext[ServerSession, LifespanResultT, RequestT]`
- Second parameter: The specific `*Params` type for that request
- Return type: The specific `*Result` type for that request

### New Constructor Parameters

```python
from mcp.shared.context import RequestContext
from mcp.server.session import ServerSession

class Server(Generic[LifespanResultT, RequestT]):
    def __init__(
        self,
        name: str,
        version: str | None = None,
        title: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        website_url: str | None = None,
        icons: list[types.Icon] | None = None,
        lifespan: Callable[
            [Server[LifespanResultT, RequestT]],
            AbstractAsyncContextManager[LifespanResultT],
        ] = lifespan,
        *,
        on_list_prompts: Callable[
            [RequestContext[ServerSession, LifespanResultT, RequestT], types.PaginatedRequestParams | None],
            Awaitable[types.ListPromptsResult],
        ] | None = None,
        on_get_prompt: Callable[
            [RequestContext[ServerSession, LifespanResultT, RequestT], types.GetPromptRequestParams],
            Awaitable[types.GetPromptResult],
        ] | None = None,
        # Resources
        on_list_resources: Callable[
            [RequestContext[ServerSession, LifespanResultT, RequestT], types.PaginatedRequestParams | None],
            Awaitable[types.ListResourcesResult],
        ] | None = None,
        on_list_resource_templates: Callable[
            [RequestContext[ServerSession, LifespanResultT, RequestT], types.PaginatedRequestParams | None],
            Awaitable[types.ListResourceTemplatesResult],
        ] | None = None,
        on_read_resource: Callable[
            [RequestContext[ServerSession, LifespanResultT, RequestT], types.ReadResourceRequestParams],
            Awaitable[types.ReadResourceResult],
        ] | None = None,
        on_subscribe_resource: Callable[
            [RequestContext[ServerSession, LifespanResultT, RequestT], types.SubscribeRequestParams],
            Awaitable[types.EmptyResult],
        ] | None = None,
        on_unsubscribe_resource: Callable[
            [RequestContext[ServerSession, LifespanResultT, RequestT], types.UnsubscribeRequestParams],
            Awaitable[types.EmptyResult],
        ] | None = None,
        # Tools
        on_list_tools: Callable[
            [RequestContext[ServerSession, LifespanResultT, RequestT], types.PaginatedRequestParams | None],
            Awaitable[types.ListToolsResult],
        ] | None = None,
        on_call_tool: Callable[
            [RequestContext[ServerSession, LifespanResultT, RequestT], types.CallToolRequestParams],
            Awaitable[types.CallToolResult],
        ] | None = None,
        # Logging
        on_set_logging_level: Callable[
            [RequestContext[ServerSession, LifespanResultT, RequestT], types.SetLevelRequestParams],
            Awaitable[types.EmptyResult],
        ] | None = None,
        # Completions
        on_completion: Callable[
            [RequestContext[ServerSession, LifespanResultT, RequestT], types.CompleteRequestParams],
            Awaitable[types.CompleteResult],
        ] | None = None,
        # Notifications
        on_progress_notification: Callable[
            [RequestContext[ServerSession, LifespanResultT, RequestT], types.ProgressNotificationParams],
            Awaitable[None],
        ] | None = None,
    ):
```

### Handler Naming Convention

| Current Decorator | Constructor Parameter | Params Type | Result Type |
|-------------------|----------------------|-------------|-------------|
| `@server.list_prompts()` | `on_list_prompts` | `PaginatedRequestParams \| None` | `ListPromptsResult` |
| `@server.get_prompt()` | `on_get_prompt` | `GetPromptRequestParams` | `GetPromptResult` |
| `@server.list_resources()` | `on_list_resources` | `PaginatedRequestParams \| None` | `ListResourcesResult` |
| `@server.list_resource_templates()` | `on_list_resource_templates` | `PaginatedRequestParams \| None` | `ListResourceTemplatesResult` |
| `@server.read_resource()` | `on_read_resource` | `ReadResourceRequestParams` | `ReadResourceResult` |
| `@server.subscribe_resource()` | `on_subscribe_resource` | `SubscribeRequestParams` | `EmptyResult` |
| `@server.unsubscribe_resource()` | `on_unsubscribe_resource` | `UnsubscribeRequestParams` | `EmptyResult` |
| `@server.list_tools()` | `on_list_tools` | `PaginatedRequestParams \| None` | `ListToolsResult` |
| `@server.call_tool()` | `on_call_tool` | `CallToolRequestParams` | `CallToolResult` |
| `@server.set_logging_level()` | `on_set_logging_level` | `SetLevelRequestParams` | `EmptyResult` |
| `@server.completion()` | `on_completion` | `CompleteRequestParams` | `CompleteResult` |
| `@server.progress_notification()` | `on_progress_notification` | `ProgressNotificationParams` | `None` |

---

## Phase 2: Constructor Handler Registration

**File:** `src/mcp/server/lowlevel/server.py`

In `__init__`, register handlers passed via constructor parameters. Each handler wrapper:
1. Sets up the request context
2. Calls the user's handler with `(context, params)`
3. Returns the result directly (no transformation needed since handler returns proper result type)

```python
def __init__(self, ...):
    # ... existing initialization ...

    # Register handlers from constructor parameters
    if on_list_prompts is not None:
        self._register_list_prompts_handler(on_list_prompts)
    if on_get_prompt is not None:
        self._register_get_prompt_handler(on_get_prompt)
    if on_list_resources is not None:
        self._register_list_resources_handler(on_list_resources)
    if on_list_resource_templates is not None:
        self._register_list_resource_templates_handler(on_list_resource_templates)
    if on_read_resource is not None:
        self._register_read_resource_handler(on_read_resource)
    if on_subscribe_resource is not None:
        self._register_subscribe_resource_handler(on_subscribe_resource)
    if on_unsubscribe_resource is not None:
        self._register_unsubscribe_resource_handler(on_unsubscribe_resource)
    if on_list_tools is not None:
        self._register_list_tools_handler(on_list_tools)
    if on_call_tool is not None:
        self._register_call_tool_handler(on_call_tool)
    if on_set_logging_level is not None:
        self._register_set_logging_level_handler(on_set_logging_level)
    if on_completion is not None:
        self._register_completion_handler(on_completion)
    if on_progress_notification is not None:
        self._register_progress_notification_handler(on_progress_notification)
```

### Internal Registration Methods

The key change is that the internal handlers now pass the context and params to the user's callback:

```python
def _register_list_tools_handler(
    self,
    func: Callable[
        [RequestContext[ServerSession, LifespanResultT, RequestT], types.PaginatedRequestParams | None],
        Awaitable[types.ListToolsResult],
    ],
) -> None:
    """Register a list tools handler."""
    logger.debug("Registering handler for ListToolsRequest")

    async def handler(req: types.ListToolsRequest) -> types.ListToolsResult:
        # Context is already set by _handle_request, retrieve it
        ctx = request_ctx.get()
        result = await func(ctx, req.params)
        # Validate tool names (existing behavior)
        for tool in result.tools:
            validate_and_warn_tool_name(tool.name)
            self._tool_cache[tool.name] = tool
        return result

    self.request_handlers[types.ListToolsRequest] = handler


def _register_call_tool_handler(
    self,
    func: Callable[
        [RequestContext[ServerSession, LifespanResultT, RequestT], types.CallToolRequestParams],
        Awaitable[types.CallToolResult],
    ],
) -> None:
    """Register a call tool handler."""
    logger.debug("Registering handler for CallToolRequest")

    async def handler(req: types.CallToolRequest) -> types.CallToolResult:
        ctx = request_ctx.get()
        # User handler is responsible for returning CallToolResult
        return await func(ctx, req.params)

    self.request_handlers[types.CallToolRequest] = handler


def _register_get_prompt_handler(
    self,
    func: Callable[
        [RequestContext[ServerSession, LifespanResultT, RequestT], types.GetPromptRequestParams],
        Awaitable[types.GetPromptResult],
    ],
) -> None:
    """Register a get prompt handler."""
    logger.debug("Registering handler for GetPromptRequest")

    async def handler(req: types.GetPromptRequest) -> types.GetPromptResult:
        ctx = request_ctx.get()
        return await func(ctx, req.params)

    self.request_handlers[types.GetPromptRequest] = handler


def _register_read_resource_handler(
    self,
    func: Callable[
        [RequestContext[ServerSession, LifespanResultT, RequestT], types.ReadResourceRequestParams],
        Awaitable[types.ReadResourceResult],
    ],
) -> None:
    """Register a read resource handler."""
    logger.debug("Registering handler for ReadResourceRequest")

    async def handler(req: types.ReadResourceRequest) -> types.ReadResourceResult:
        ctx = request_ctx.get()
        return await func(ctx, req.params)

    self.request_handlers[types.ReadResourceRequest] = handler
```

---

## Phase 3: Deprecate Decorator Methods

**File:** `src/mcp/server/lowlevel/server.py`

Keep decorators for backward compatibility but mark as deprecated:

```python
def list_tools(self):
    """Register a list tools handler.

    .. deprecated::
        Use the `on_list_tools` constructor parameter instead.
    """
    warnings.warn(
        "The @server.list_tools() decorator is deprecated. "
        "Use the on_list_tools constructor parameter instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    def decorator(
        func: Callable[[], Awaitable[list[types.Tool]]]
        | Callable[[types.ListToolsRequest], Awaitable[types.ListToolsResult]],
    ):
        # Keep existing decorator logic for backward compatibility
        wrapper = create_call_wrapper(func, types.ListToolsRequest)

        async def handler(req: types.ListToolsRequest):
            result = await wrapper(req)
            if isinstance(result, types.ListToolsResult):
                for tool in result.tools:
                    validate_and_warn_tool_name(tool.name)
                    self._tool_cache[tool.name] = tool
                return result
            else:
                self._tool_cache.clear()
                for tool in result:
                    validate_and_warn_tool_name(tool.name)
                    self._tool_cache[tool.name] = tool
                return types.ListToolsResult(tools=result)

        self.request_handlers[types.ListToolsRequest] = handler
        return func

    return decorator
```

---

## Phase 4: Update Tests

**File:** `tests/server/lowlevel/test_constructor_handlers.py` (create new)

### Add Tests for Constructor-Based Registration

```python
import pytest
from mcp.server.lowlevel import Server
from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext
import mcp.types as types
from typing import Any


@pytest.mark.anyio
async def test_constructor_list_tools_handler():
    """Test registering list_tools via constructor."""

    async def list_tools(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="test-tool", description="A test tool")]
        )

    server = Server(
        name="test-server",
        on_list_tools=list_tools,
    )

    assert types.ListToolsRequest in server.request_handlers


@pytest.mark.anyio
async def test_constructor_call_tool_handler():
    """Test registering call_tool via constructor."""

    async def call_tool(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Called {params.name}")],
        )

    server = Server(
        name="test-server",
        on_call_tool=call_tool,
    )

    assert types.CallToolRequest in server.request_handlers


@pytest.mark.anyio
async def test_decorator_deprecation_warning():
    """Test that decorators emit deprecation warnings."""
    server = Server(name="test-server")

    with pytest.warns(DeprecationWarning, match="on_list_tools constructor parameter"):
        @server.list_tools()
        async def list_tools():
            return []
```

### E2E Tests Using mcp.client.Client

Follow the pattern from `tests/client/test_client.py`:

```python
@pytest.mark.anyio
async def test_constructor_tools_e2e():
    """E2E test for constructor-based tool handlers."""

    async def list_tools(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="echo",
                    description="Echo input",
                    input_schema={
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                    },
                )
            ]
        )

    async def call_tool(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        if params.name == "echo":
            msg = (params.arguments or {}).get("message", "")
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=msg)],
            )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Unknown tool: {params.name}")],
            is_error=True,
        )

    server = Server(
        name="test-server",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )

    # Use in-memory transport for testing
    async with create_client_server_pair(server) as (client, _):
        tools = await client.list_tools()
        assert len(tools.tools) == 1
        assert tools.tools[0].name == "echo"

        result = await client.call_tool("echo", {"message": "hello"})
        assert result.content[0].text == "hello"
```

---

## Phase 5: Update Documentation

### Update Module Docstring

**File:** `src/mcp/server/lowlevel/server.py`

```python
"""MCP Server Module

This module provides a framework for creating an MCP (Model Context Protocol) server.

Usage:
1. Define handler functions that receive (context, params) and return result objects:

   async def list_tools(
       ctx: RequestContext[ServerSession, Any, Any],
       params: types.PaginatedRequestParams | None,
   ) -> types.ListToolsResult:
       return types.ListToolsResult(tools=[
           types.Tool(name="my-tool", description="...")
       ])

   async def call_tool(
       ctx: RequestContext[ServerSession, Any, Any],
       params: types.CallToolRequestParams,
   ) -> types.CallToolResult:
       # Access context for session, lifespan data, etc.
       db = ctx.lifespan_context["db"]
       return types.CallToolResult(content=[...])

2. Create a Server instance with handlers:

   server = Server(
       name="your_server_name",
       on_list_tools=list_tools,
       on_call_tool=call_tool,
   )

3. Run the server:

   async def main():
       async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
           await server.run(
               read_stream,
               write_stream,
               server.create_initialization_options(),
           )

   asyncio.run(main())

Note: The decorator-based API is deprecated but still supported for backward compatibility.
"""
```

### Update Migration Guide

**File:** `docs/migration.md`

Add a new section documenting the change:

```markdown
## Low-Level Server API Changes

### Constructor-Based Handler Registration

The low-level `Server` class now supports constructor-based handler registration,
which is the recommended approach. The decorator-based API is deprecated.

**Before (Deprecated):**
```python
server = Server("my-server")

@server.list_tools()
async def list_tools():
    return [types.Tool(name="tool", description="...")]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    return {"result": "..."}
```

**After (Recommended):**
```python
async def list_tools(
    ctx: RequestContext[ServerSession, Any, Any],
    params: types.PaginatedRequestParams | None,
) -> types.ListToolsResult:
    return types.ListToolsResult(tools=[
        types.Tool(name="tool", description="...")
    ])

async def call_tool(
    ctx: RequestContext[ServerSession, Any, Any],
    params: types.CallToolRequestParams,
) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text="result")]
    )

server = Server(
    "my-server",
    on_list_tools=list_tools,
    on_call_tool=call_tool,
)
```

**Key differences:**
1. Handlers receive `(context, params)` instead of extracted arguments
2. Handlers return proper result types (`ListToolsResult`, `CallToolResult`, etc.)
3. Context provides access to session, lifespan data, and request metadata

**Migration steps:**
1. Update handler signatures to accept `(ctx, params)`
2. Update return types to use proper result classes
3. Pass handlers to the Server constructor using `on_*` parameters
4. Remove decorator calls

**Benefits:**
- Context available in all handlers (session, lifespan data, request metadata)
- Type-safe params and return types
- Clearer dependencies at construction time
- Better testability (handlers can be mocked/replaced)
```

---

## Phase 6: Implementation Checklist

### Files to Modify

- [ ] `src/mcp/server/lowlevel/server.py` - Main server class
- [ ] `docs/migration.md` - Document breaking changes

### Files to Create/Update for Tests

- [ ] `tests/server/lowlevel/test_constructor_handlers.py` - New tests for constructor API
- [ ] Update existing tests in `tests/server/` to use new API where appropriate

### Implementation Order

1. **Add private registration methods** (`_register_*_handler`) that accept the new signature
2. **Update constructor** to accept handler parameters with inline types
3. **Register handlers in constructor** by calling private methods
4. **Deprecate decorator methods** with warnings
5. **Write tests** for new constructor-based API
6. **Update documentation** and migration guide
7. **Run full test suite** to ensure backward compatibility

---

## Phase 7: Backward Compatibility Strategy

### Approach: Deprecation with Migration Period

1. **Keep decorators working** - They should continue to function but emit deprecation warnings
2. **Allow mixed usage** - Users can use constructor params for some handlers and decorators for others (during migration)
3. **Future removal** - Plan to remove decorator methods in a future major version

### Conflict Resolution

If a handler is registered both via constructor and decorator, raise an error:

```python
def _register_list_tools_handler(self, func) -> None:
    if types.ListToolsRequest in self.request_handlers:
        raise ValueError(
            "A list_tools handler is already registered. "
            "Cannot register multiple handlers for the same request type."
        )
    # ... rest of registration ...
```

---

## Summary of Changes

| Component | Change Type | Description |
|-----------|-------------|-------------|
| `Server.__init__` | **Addition** | New `on_*` parameters with inline types for all handlers |
| `Server._register_*_handler` | **Addition** | Private methods for handler registration |
| `Server.list_tools`, etc. | **Deprecation** | Decorator methods emit warnings |
| Tests | **Addition** | New tests for constructor-based API |
| Documentation | **Update** | Migration guide and module docstring |

---

## Handler Signature Reference

All handlers follow the pattern: `(context, params) -> result`

| Handler | Context Type | Params Type | Return Type |
|---------|--------------|-------------|-------------|
| `on_list_prompts` | `RequestContext[...]` | `PaginatedRequestParams \| None` | `ListPromptsResult` |
| `on_get_prompt` | `RequestContext[...]` | `GetPromptRequestParams` | `GetPromptResult` |
| `on_list_resources` | `RequestContext[...]` | `PaginatedRequestParams \| None` | `ListResourcesResult` |
| `on_list_resource_templates` | `RequestContext[...]` | `PaginatedRequestParams \| None` | `ListResourceTemplatesResult` |
| `on_read_resource` | `RequestContext[...]` | `ReadResourceRequestParams` | `ReadResourceResult` |
| `on_subscribe_resource` | `RequestContext[...]` | `SubscribeRequestParams` | `EmptyResult` |
| `on_unsubscribe_resource` | `RequestContext[...]` | `UnsubscribeRequestParams` | `EmptyResult` |
| `on_list_tools` | `RequestContext[...]` | `PaginatedRequestParams \| None` | `ListToolsResult` |
| `on_call_tool` | `RequestContext[...]` | `CallToolRequestParams` | `CallToolResult` |
| `on_set_logging_level` | `RequestContext[...]` | `SetLevelRequestParams` | `EmptyResult` |
| `on_completion` | `RequestContext[...]` | `CompleteRequestParams` | `CompleteResult` |
| `on_progress_notification` | `RequestContext[...]` | `ProgressNotificationParams` | `None` |

Where `RequestContext[...]` is `RequestContext[ServerSession, LifespanResultT, RequestT]`.

---

## Open Questions

1. **Experimental handlers** - Should `server.experimental` handlers also move to constructor parameters, or stay separate?

2. **Should we keep the decorator API indefinitely?** Or plan a hard removal in v2.0?
