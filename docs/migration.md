# Migration Guide: v1 to v2

This guide covers the breaking changes introduced in v2 of the MCP Python SDK and how to update your code.

## Overview

Version 2 of the MCP Python SDK introduces several breaking changes to improve the API, align with the MCP specification, and provide better type safety.

## Breaking Changes

### `streamablehttp_client` removed

The deprecated `streamablehttp_client` function has been removed. Use `streamable_http_client` instead.

**Before (v1):**

```python
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client(
    url="http://localhost:8000/mcp",
    headers={"Authorization": "Bearer token"},
    timeout=30,
    sse_read_timeout=300,
    auth=my_auth,
) as (read_stream, write_stream, get_session_id):
    ...
```

**After (v2):**

```python
import httpx
from mcp.client.streamable_http import streamable_http_client

# Configure headers, timeout, and auth on the httpx.AsyncClient
http_client = httpx.AsyncClient(
    headers={"Authorization": "Bearer token"},
    timeout=httpx.Timeout(30, read=300),
    auth=my_auth,
)

async with http_client:
    async with streamable_http_client(
        url="http://localhost:8000/mcp",
        http_client=http_client,
    ) as (read_stream, write_stream):
        ...
```

### `get_session_id` callback removed from `streamable_http_client`

The `get_session_id` callback (third element of the returned tuple) has been removed from `streamable_http_client`. The function now returns a 2-tuple `(read_stream, write_stream)` instead of a 3-tuple.

If you need to capture the session ID (e.g., for session resumption testing), you can use httpx event hooks to capture it from the response headers:

**Before (v1):**

```python
from mcp.client.streamable_http import streamable_http_client

async with streamable_http_client(url) as (read_stream, write_stream, get_session_id):
    async with ClientSession(read_stream, write_stream) as session:
        await session.initialize()
        session_id = get_session_id()  # Get session ID via callback
```

**After (v2):**

```python
import httpx
from mcp.client.streamable_http import streamable_http_client

# Option 1: Simply ignore if you don't need the session ID
async with streamable_http_client(url) as (read_stream, write_stream):
    async with ClientSession(read_stream, write_stream) as session:
        await session.initialize()

# Option 2: Capture session ID via httpx event hooks if needed
captured_session_ids: list[str] = []

async def capture_session_id(response: httpx.Response) -> None:
    session_id = response.headers.get("mcp-session-id")
    if session_id:
        captured_session_ids.append(session_id)

http_client = httpx.AsyncClient(
    event_hooks={"response": [capture_session_id]},
    follow_redirects=True,
)

async with http_client:
    async with streamable_http_client(url, http_client=http_client) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            session_id = captured_session_ids[0] if captured_session_ids else None
```

### `StreamableHTTPTransport` parameters removed

The `headers`, `timeout`, `sse_read_timeout`, and `auth` parameters have been removed from `StreamableHTTPTransport`. Configure these on the `httpx.AsyncClient` instead (see example above).

### Removed type aliases and classes

The following deprecated type aliases and classes have been removed from `mcp.types`:

| Removed | Replacement |
|---------|-------------|
| `Content` | `ContentBlock` |
| `ResourceReference` | `ResourceTemplateReference` |
| `Cursor` | Use `str` directly |
| `MethodT` | Internal TypeVar, not intended for public use |
| `RequestParamsT` | Internal TypeVar, not intended for public use |
| `NotificationParamsT` | Internal TypeVar, not intended for public use |

**Before (v1):**

```python
from mcp.types import Content, ResourceReference, Cursor
```

**After (v2):**

```python
from mcp.types import ContentBlock, ResourceTemplateReference
# Use `str` instead of `Cursor` for pagination cursors
```

### `args` parameter removed from `ClientSessionGroup.call_tool()`

The deprecated `args` parameter has been removed from `ClientSessionGroup.call_tool()`. Use `arguments` instead.

**Before (v1):**

```python
result = await session_group.call_tool("my_tool", args={"key": "value"})
```

**After (v2):**

```python
result = await session_group.call_tool("my_tool", arguments={"key": "value"})
```

### `cursor` parameter removed from `ClientSession` list methods

The deprecated `cursor` parameter has been removed from the following `ClientSession` methods:

- `list_resources()`
- `list_resource_templates()`
- `list_prompts()`
- `list_tools()`

Use `params=PaginatedRequestParams(cursor=...)` instead.

**Before (v1):**

```python
result = await session.list_resources(cursor="next_page_token")
result = await session.list_tools(cursor="next_page_token")
```

**After (v2):**

```python
from mcp.types import PaginatedRequestParams

result = await session.list_resources(params=PaginatedRequestParams(cursor="next_page_token"))
result = await session.list_tools(params=PaginatedRequestParams(cursor="next_page_token"))
```

### `McpError` renamed to `MCPError`

The `McpError` exception class has been renamed to `MCPError` for consistent naming with the MCP acronym style used throughout the SDK.

**Before (v1):**

```python
from mcp.shared.exceptions import McpError

try:
    result = await session.call_tool("my_tool")
except McpError as e:
    print(f"Error: {e.error.message}")
```

**After (v2):**

```python
from mcp.shared.exceptions import MCPError

try:
    result = await session.call_tool("my_tool")
except MCPError as e:
    print(f"Error: {e.message}")
```

`MCPError` is also exported from the top-level `mcp` package:

```python
from mcp import MCPError
```

### `FastMCP` renamed to `MCPServer`

The `FastMCP` class has been renamed to `MCPServer` to better reflect its role as the main server class in the SDK. This is a simple rename with no functional changes to the class itself.

**Before (v1):**

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Demo")
```

**After (v2):**

```python
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("Demo")
```

### `mount_path` parameter removed from MCPServer

The `mount_path` parameter has been removed from `MCPServer.__init__()`, `MCPServer.run()`, `MCPServer.run_sse_async()`, and `MCPServer.sse_app()`. It was also removed from the `Settings` class.

This parameter was redundant because the SSE transport already handles sub-path mounting via ASGI's standard `root_path` mechanism. When using Starlette's `Mount("/path", app=mcp.sse_app())`, Starlette automatically sets `root_path` in the ASGI scope, and the `SseServerTransport` uses this to construct the correct message endpoint path.

### Transport-specific parameters moved from MCPServer constructor to run()/app methods

Transport-specific parameters have been moved from the `MCPServer` constructor to the `run()`, `sse_app()`, and `streamable_http_app()` methods. This provides better separation of concerns - the constructor now only handles server identity and authentication, while transport configuration is passed when starting the server.

**Parameters moved:**

- `host`, `port` - HTTP server binding
- `sse_path`, `message_path` - SSE transport paths
- `streamable_http_path` - StreamableHTTP endpoint path
- `json_response`, `stateless_http` - StreamableHTTP behavior
- `event_store`, `retry_interval` - StreamableHTTP event handling
- `transport_security` - DNS rebinding protection

**Before (v1):**

```python
from mcp.server.fastmcp import FastMCP

# Transport params in constructor
mcp = FastMCP("Demo", json_response=True, stateless_http=True)
mcp.run(transport="streamable-http")

# Or for SSE
mcp = FastMCP("Server", host="0.0.0.0", port=9000, sse_path="/events")
mcp.run(transport="sse")
```

**After (v2):**

```python
from mcp.server.mcpserver import MCPServer

# Transport params passed to run()
mcp = MCPServer("Demo")
mcp.run(transport="streamable-http", json_response=True, stateless_http=True)

# Or for SSE
mcp = MCPServer("Server")
mcp.run(transport="sse", host="0.0.0.0", port=9000, sse_path="/events")
```

**For mounted apps:**

When mounting in a Starlette app, pass transport params to the app methods:

```python
# Before (v1)
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("App", json_response=True)
app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app())])

# After (v2)
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("App")
app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app(json_response=True))])
```

**Note:** DNS rebinding protection is automatically enabled when `host` is `127.0.0.1`, `localhost`, or `::1`. This now happens in `sse_app()` and `streamable_http_app()` instead of the constructor.

### Replace `RootModel` by union types with `TypeAdapter` validation

The following union types are no longer `RootModel` subclasses:

- `ClientRequest`
- `ServerRequest`
- `ClientNotification`
- `ServerNotification`
- `ClientResult`
- `ServerResult`
- `JSONRPCMessage`

This means you can no longer access `.root` on these types or use `model_validate()` directly on them. Instead, use the provided `TypeAdapter` instances for validation.

**Before (v1):**

```python
from mcp.types import ClientRequest, ServerNotification

# Using RootModel.model_validate()
request = ClientRequest.model_validate(data)
actual_request = request.root  # Accessing the wrapped value

notification = ServerNotification.model_validate(data)
actual_notification = notification.root
```

**After (v2):**

```python
from mcp.types import client_request_adapter, server_notification_adapter

# Using TypeAdapter.validate_python()
request = client_request_adapter.validate_python(data)
# No .root access needed - request is the actual type

notification = server_notification_adapter.validate_python(data)
# No .root access needed - notification is the actual type
```

**Available adapters:**

| Union Type | Adapter |
|------------|---------|
| `ClientRequest` | `client_request_adapter` |
| `ServerRequest` | `server_request_adapter` |
| `ClientNotification` | `client_notification_adapter` |
| `ServerNotification` | `server_notification_adapter` |
| `ClientResult` | `client_result_adapter` |
| `ServerResult` | `server_result_adapter` |
| `JSONRPCMessage` | `jsonrpc_message_adapter` |

All adapters are exported from `mcp.types`.

### `RequestParams.Meta` replaced with `RequestParamsMeta` TypedDict

The nested `RequestParams.Meta` Pydantic model class has been replaced with a top-level `RequestParamsMeta` TypedDict. This affects the `ctx.meta` field in request handlers and any code that imports or references this type.

**Key changes:**

- `RequestParams.Meta` (Pydantic model) → `RequestParamsMeta` (TypedDict)
- Attribute access (`meta.progress_token`) → Dictionary access (`meta.get("progress_token")`)
- `progress_token` field changed from `ProgressToken | None = None` to `NotRequired[ProgressToken]`

**In request context handlers:**

```python
# Before (v1)
@server.call_tool()
async def handle_tool(name: str, arguments: dict) -> list[TextContent]:
    ctx = server.request_context
    if ctx.meta and ctx.meta.progress_token:
        await ctx.session.send_progress_notification(ctx.meta.progress_token, 0.5, 100)

# After (v2)
async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    if ctx.meta and "progress_token" in ctx.meta:
        await ctx.session.send_progress_notification(ctx.meta["progress_token"], 0.5, 100)
    ...

server = Server("my-server", on_call_tool=handle_call_tool)
```

### `RequestContext` and `ProgressContext` type parameters simplified

The `RequestContext` class has been split to separate shared fields from server-specific fields. The shared `RequestContext` now only takes 1 type parameter (the session type) instead of 3.

**`RequestContext` changes:**

- Type parameters reduced from `RequestContext[SessionT, LifespanContextT, RequestT]` to `RequestContext[SessionT]`
- Server-specific fields (`lifespan_context`, `experimental`, `request`, `close_sse_stream`, `close_standalone_sse_stream`) moved to new `ServerRequestContext` class in `mcp.server.context`

**`ProgressContext` changes:**

- Type parameters reduced from `ProgressContext[SendRequestT, SendNotificationT, SendResultT, ReceiveRequestT, ReceiveNotificationT]` to `ProgressContext[SessionT]`

**Before (v1):**

```python
from mcp.client.session import ClientSession
from mcp.shared.context import RequestContext, LifespanContextT, RequestT
from mcp.shared.progress import ProgressContext

# RequestContext with 3 type parameters
ctx: RequestContext[ClientSession, LifespanContextT, RequestT]

# ProgressContext with 5 type parameters
progress_ctx: ProgressContext[SendRequestT, SendNotificationT, SendResultT, ReceiveRequestT, ReceiveNotificationT]
```

**After (v2):**

```python
from mcp.client.context import ClientRequestContext
from mcp.client.session import ClientSession
from mcp.server.context import ServerRequestContext, LifespanContextT, RequestT
from mcp.shared.progress import ProgressContext

# For client-side context (sampling, elicitation, list_roots callbacks)
ctx: ClientRequestContext

# For server-specific context with lifespan and request types
server_ctx: ServerRequestContext[LifespanContextT, RequestT]

# ProgressContext with 1 type parameter
progress_ctx: ProgressContext[ClientSession]
```

### Resource URI type changed from `AnyUrl` to `str`

The `uri` field on resource-related types now uses `str` instead of Pydantic's `AnyUrl`. This aligns with the [MCP specification schema](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/draft/schema.ts) which defines URIs as plain strings (`uri: string`) without strict URL validation. This change allows relative paths like `users/me` that were previously rejected.

**Before (v1):**

```python
from pydantic import AnyUrl
from mcp.types import Resource

# Required wrapping in AnyUrl
resource = Resource(name="test", uri=AnyUrl("users/me"))  # Would fail validation
```

**After (v2):**

```python
from mcp.types import Resource

# Plain strings accepted
resource = Resource(name="test", uri="users/me")  # Works
resource = Resource(name="test", uri="custom://scheme")  # Works
resource = Resource(name="test", uri="https://example.com")  # Works
```

If your code passes `AnyUrl` objects to URI fields, convert them to strings:

```python
# If you have an AnyUrl from elsewhere
uri = str(my_any_url)  # Convert to string
```

Affected types:

- `Resource.uri`
- `ReadResourceRequestParams.uri`
- `ResourceContents.uri` (and subclasses `TextResourceContents`, `BlobResourceContents`)
- `SubscribeRequestParams.uri`
- `UnsubscribeRequestParams.uri`
- `ResourceUpdatedNotificationParams.uri`

The `Client` and `ClientSession` methods `read_resource()`, `subscribe_resource()`, and `unsubscribe_resource()` now only accept `str` for the `uri` parameter. If you were passing `AnyUrl` objects, convert them to strings:

```python
# Before (v1)
from pydantic import AnyUrl

await client.read_resource(AnyUrl("test://resource"))

# After (v2)
await client.read_resource("test://resource")
# Or if you have an AnyUrl from elsewhere:
await client.read_resource(str(my_any_url))
```

### Lowlevel `Server`: constructor parameters are now keyword-only

All parameters after `name` are now keyword-only. If you were passing `version` or other parameters positionally, use keyword arguments instead:

```python
# Before (v1)
server = Server("my-server", "1.0")

# After (v2)
server = Server("my-server", version="1.0")
```

### Lowlevel `Server`: decorator-based handlers replaced with constructor `on_*` params

The lowlevel `Server` class no longer uses decorator methods for handler registration. Instead, handlers are passed as `on_*` keyword arguments to the constructor.

**Before (v1):**

```python
from mcp.server.lowlevel.server import Server

server = Server("my-server")

@server.list_tools()
async def handle_list_tools():
    return [types.Tool(name="my_tool", description="A tool", inputSchema={})]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict):
    return [types.TextContent(type="text", text=f"Called {name}")]
```

**After (v2):**

```python
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

async def handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[Tool(name="my_tool", description="A tool", inputSchema={})])


async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=f"Called {params.name}")],
        is_error=False,
    )

server = Server("my-server", on_list_tools=handle_list_tools, on_call_tool=handle_call_tool)
```

**Key differences:**

- Handlers receive `(ctx, params)` instead of the full request object or unpacked arguments. `ctx` is a `RequestContext` with `session`, `lifespan_context`, and `experimental` fields (plus `request_id`, `meta`, etc. for request handlers). `params` is the typed request params object.
- Handlers return the full result type (e.g. `ListToolsResult`) rather than unwrapped values (e.g. `list[Tool]`).
- The automatic `jsonschema` input/output validation that the old `call_tool()` decorator performed has been removed. There is no built-in replacement — if you relied on schema validation in the lowlevel server, you will need to validate inputs yourself in your handler.

**Notification handlers:**

```python
from mcp.server import Server, ServerRequestContext
from mcp.types import ProgressNotificationParams


async def handle_progress(ctx: ServerRequestContext, params: ProgressNotificationParams) -> None:
    print(f"Progress: {params.progress}/{params.total}")

server = Server("my-server", on_progress=handle_progress)
```

### Lowlevel `Server`: automatic return value wrapping removed

The old decorator-based handlers performed significant automatic wrapping of return values. This magic has been removed — handlers now return fully constructed result types. If you want these conveniences, use `MCPServer` (previously `FastMCP`) instead of the lowlevel `Server`.

**`call_tool()` — structured output wrapping removed:**

The old decorator accepted several return types and auto-wrapped them into `CallToolResult`:

```python
# Before (v1) — returning a dict auto-wrapped into structured_content + JSON TextContent
@server.call_tool()
async def handle(name: str, arguments: dict) -> dict:
    return {"temperature": 22.5, "city": "London"}

# Before (v1) — returning a list auto-wrapped into CallToolResult.content
@server.call_tool()
async def handle(name: str, arguments: dict) -> list[TextContent]:
    return [TextContent(type="text", text="Done")]
```

```python
# After (v2) — construct the full result yourself
import json

async def handle(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    data = {"temperature": 22.5, "city": "London"}
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data, indent=2))],
        structured_content=data,
    )
```

Note: `params.arguments` can be `None` (the old decorator defaulted it to `{}`). Use `params.arguments or {}` to preserve the old behavior.

**`read_resource()` — content type wrapping removed:**

The old decorator auto-wrapped `str` into `TextResourceContents` and `bytes` into `BlobResourceContents` (with base64 encoding), and applied a default mime type of `text/plain`:

```python
# Before (v1) — str/bytes auto-wrapped with mime type defaulting
@server.read_resource()
async def handle(uri: str) -> str:
    return "file contents"

@server.read_resource()
async def handle(uri: str) -> bytes:
    return b"\x89PNG..."
```

```python
# After (v2) — construct TextResourceContents or BlobResourceContents yourself
import base64

async def handle_read(ctx: ServerRequestContext, params: ReadResourceRequestParams) -> ReadResourceResult:
    # Text content
    return ReadResourceResult(
        contents=[TextResourceContents(uri=str(params.uri), text="file contents", mime_type="text/plain")]
    )

async def handle_read(ctx: ServerRequestContext, params: ReadResourceRequestParams) -> ReadResourceResult:
    # Binary content — you must base64-encode it yourself
    return ReadResourceResult(
        contents=[BlobResourceContents(
            uri=str(params.uri),
            blob=base64.b64encode(b"\x89PNG...").decode("utf-8"),
            mime_type="image/png",
        )]
    )
```

**`list_tools()`, `list_resources()`, `list_prompts()` — list wrapping removed:**

The old decorators accepted bare lists and wrapped them into the result type:

```python
# Before (v1)
@server.list_tools()
async def handle() -> list[Tool]:
    return [Tool(name="my_tool", ...)]

# After (v2)
async def handle(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[Tool(name="my_tool", ...)])
```

**Using `MCPServer` instead:**

If you prefer the convenience of automatic wrapping, use `MCPServer` which still provides these features through its `@mcp.tool()`, `@mcp.resource()`, and `@mcp.prompt()` decorators. The lowlevel `Server` is intentionally minimal — it provides no magic and gives you full control over the MCP protocol types.

### Lowlevel `Server`: `request_context` property removed

The `server.request_context` property has been removed. Request context is now passed directly to handlers as the first argument (`ctx`). The `request_ctx` module-level contextvar still exists but should not be needed — use `ctx` directly instead.

**Before (v1):**

```python
from mcp.server.lowlevel.server import request_ctx

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict):
    ctx = server.request_context  # or request_ctx.get()
    await ctx.session.send_log_message(level="info", data="Processing...")
    return [types.TextContent(type="text", text="Done")]
```

**After (v2):**

```python
from mcp.server import ServerRequestContext
from mcp.types import CallToolRequestParams, CallToolResult, TextContent


async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    await ctx.session.send_log_message(level="info", data="Processing...")
    return CallToolResult(
        content=[TextContent(type="text", text="Done")],
        is_error=False,
    )
```

### `RequestContext`: request-specific fields are now optional

The `RequestContext` class now uses optional fields for request-specific data (`request_id`, `meta`, etc.) so it can be used for both request and notification handlers. In notification handlers, these fields are `None`.

```python
from mcp.server import ServerRequestContext

# request_id, meta, etc. are available in request handlers
# but None in notification handlers
```

### Experimental: task handler decorators removed

The experimental decorator methods on `ExperimentalHandlers` (`@server.experimental.list_tasks()`, `@server.experimental.get_task()`, etc.) have been removed.

Default task handlers are still registered automatically via `server.experimental.enable_tasks()`. Custom handlers can be passed as `on_*` kwargs to override specific defaults.

**Before (v1):**

```python
server = Server("my-server")
server.experimental.enable_tasks(task_store)

@server.experimental.get_task()
async def custom_get_task(request: GetTaskRequest) -> GetTaskResult:
    ...
```

**After (v2):**

```python
from mcp.server import Server, ServerRequestContext
from mcp.types import GetTaskRequestParams, GetTaskResult


async def custom_get_task(ctx: ServerRequestContext, params: GetTaskRequestParams) -> GetTaskResult:
    ...


server = Server("my-server")
server.experimental.enable_tasks(on_get_task=custom_get_task)
```

## Deprecations

<!-- Add deprecations below -->

## Bug Fixes

### Extra fields no longer allowed on top-level MCP types

MCP protocol types no longer accept arbitrary extra fields at the top level. This matches the MCP specification which only allows extra fields within `_meta` objects, not on the types themselves.

```python
# This will now raise a validation error
from mcp.types import CallToolRequestParams

params = CallToolRequestParams(
    name="my_tool",
    arguments={},
    unknown_field="value",  # ValidationError: extra fields not permitted
)

# Extra fields are still allowed in _meta
params = CallToolRequestParams(
    name="my_tool",
    arguments={},
    _meta={"progressToken": "tok", "customField": "value"},  # OK
)
```

## New Features

### `streamable_http_app()` available on lowlevel Server

The `streamable_http_app()` method is now available directly on the lowlevel `Server` class, not just `MCPServer`. This allows using the streamable HTTP transport without the MCPServer wrapper.

```python
from mcp.server import Server, ServerRequestContext
from mcp.types import ListToolsResult, PaginatedRequestParams


async def handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[...])


server = Server("my-server", on_list_tools=handle_list_tools)

app = server.streamable_http_app(
    streamable_http_path="/mcp",
    json_response=False,
    stateless_http=False,
)
```

The lowlevel `Server` also now exposes a `session_manager` property to access the `StreamableHTTPSessionManager` after calling `streamable_http_app()`.

## Need Help?

If you encounter issues during migration:

1. Check the [API Reference](api.md) for updated method signatures
2. Review the [examples](https://github.com/modelcontextprotocol/python-sdk/tree/main/examples) for updated usage patterns
3. Open an issue on [GitHub](https://github.com/modelcontextprotocol/python-sdk/issues) if you find a bug or need further assistance
