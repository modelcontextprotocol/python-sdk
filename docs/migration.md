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
    follow_redirects=True,
)

async with http_client:
    async with streamable_http_client(
        url="http://localhost:8000/mcp",
        http_client=http_client,
    ) as (read_stream, write_stream):
        ...
```

v1's internal client set `follow_redirects=True`; set it explicitly when supplying your own `httpx.AsyncClient` to preserve that behavior.

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

Note: `sse_client` retains its `headers`, `timeout`, `sse_read_timeout`, and `auth` parameters — only the streamable HTTP transport changed.

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

### Field names changed from camelCase to snake_case

All Pydantic model fields in `mcp.types` now use snake_case names for Python attribute access. The JSON wire format is unchanged — serialization still uses camelCase via Pydantic aliases.

**Before (v1):**

```python
result = await session.call_tool("my_tool", {"x": 1})
if result.isError:
    ...

tools = await session.list_tools()
cursor = tools.nextCursor
schema = tools.tools[0].inputSchema
```

**After (v2):**

```python
result = await session.call_tool("my_tool", {"x": 1})
if result.is_error:
    ...

tools = await session.list_tools()
cursor = tools.next_cursor
schema = tools.tools[0].input_schema
```

Common renames:

| v1 (camelCase) | v2 (snake_case) |
|----------------|-----------------|
| `inputSchema` | `input_schema` |
| `outputSchema` | `output_schema` |
| `isError` | `is_error` |
| `nextCursor` | `next_cursor` |
| `mimeType` | `mime_type` |
| `structuredContent` | `structured_content` |
| `serverInfo` | `server_info` |
| `protocolVersion` | `protocol_version` |
| `uriTemplate` | `uri_template` |
| `listChanged` | `list_changed` |
| `progressToken` | `progress_token` |

Because `populate_by_name=True` is set, the old camelCase names still work as constructor kwargs (e.g., `Tool(inputSchema={...})` is accepted), but attribute access must use snake_case (`tool.input_schema`).

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

### `ClientSession.get_server_capabilities()` replaced by `initialize_result` property

`ClientSession` now stores the full `InitializeResult` via an `initialize_result` property. This provides access to `server_info`, `capabilities`, `instructions`, and the negotiated `protocol_version` through a single property. The `get_server_capabilities()` method has been removed.

**Before (v1):**

```python
capabilities = session.get_server_capabilities()
# server_info, instructions, protocol_version were not stored — had to capture initialize() return value
```

**After (v2):**

```python
result = session.initialize_result
if result is not None:
    capabilities = result.capabilities
    server_info = result.server_info
    instructions = result.instructions
    version = result.protocol_version
```

The high-level `Client.initialize_result` returns the same `InitializeResult` but is non-nullable — initialization is guaranteed inside the context manager, so no `None` check is needed. This replaces v1's `Client.server_capabilities`; use `client.initialize_result.capabilities` instead.

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

The constructor signature also changed — it now takes `code`, `message`, and optional `data` directly instead of wrapping an `ErrorData`:

**Before (v1):**

```python
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData, INVALID_REQUEST

raise McpError(ErrorData(code=INVALID_REQUEST, message="bad input"))
```

**After (v2):**

```python
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_REQUEST

raise MCPError(INVALID_REQUEST, "bad input")
# or, if you already have an ErrorData:
raise MCPError.from_error_data(error_data)
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
from mcp.server.mcpserver import MCPServer, Context

mcp = MCPServer("Demo")
```

`Context` is the type annotation for the `ctx` parameter injected into tools, resources, and prompts (see [`get_context()` removed](#mcpserverget_context-removed) below).

All submodules under `mcp.server.fastmcp.*` are now under `mcp.server.mcpserver.*` with the same structure. Common imports:

- `Image`, `Audio` — from `mcp.server.mcpserver` (or `.utilities.types`)
- `UserMessage`, `AssistantMessage` — from `mcp.server.mcpserver.prompts.base`
- `ToolError`, `ResourceError` — from `mcp.server.mcpserver.exceptions`

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

If you were mutating these via `mcp.settings` after construction (e.g., `mcp.settings.port = 9000`), pass them to `run()` / `sse_app()` / `streamable_http_app()` instead — these fields no longer exist on `Settings`. The `debug` and `log_level` parameters remain on the constructor.

### `MCPServer.get_context()` removed

`MCPServer.get_context()` has been removed. Context is now injected by the framework and passed explicitly — there is no ambient ContextVar to read from.

**If you were calling `get_context()` from inside a tool/resource/prompt:** use the `ctx: Context` parameter injection instead.

**Before (v1):**

```python
@mcp.tool()
async def my_tool(x: int) -> str:
    ctx = mcp.get_context()
    await ctx.info("Processing...")
    return str(x)
```

**After (v2):**

```python
from mcp.server.mcpserver import Context

@mcp.tool()
async def my_tool(x: int, ctx: Context) -> str:
    await ctx.info("Processing...")
    return str(x)
```

### `MCPServer.call_tool()`, `read_resource()`, `get_prompt()` now accept a `context` parameter

`MCPServer.call_tool()`, `MCPServer.read_resource()`, and `MCPServer.get_prompt()` now accept an optional `context: Context | None = None` parameter. The framework passes this automatically during normal request handling. If you call these methods directly and omit `context`, a Context with no active request is constructed for you — tools that don't use `ctx` work normally, but any attempt to use `ctx.session`, `ctx.request_id`, etc. will raise.

The internal layers (`ToolManager.call_tool`, `Tool.run`, `Prompt.render`, `ResourceTemplate.create_resource`, etc.) now require `context` as a positional argument.

### Registering lowlevel handlers on `MCPServer` (workaround)

`MCPServer` does not expose public APIs for `subscribe_resource`, `unsubscribe_resource`, or `set_logging_level` handlers. In v1, the workaround was to reach into the private lowlevel server and use its decorator methods:

**Before (v1):**

```python
@mcp._mcp_server.set_logging_level()  # pyright: ignore[reportPrivateUsage]
async def handle_set_logging_level(level: str) -> None:
    ...

mcp._mcp_server.subscribe_resource()(handle_subscribe)  # pyright: ignore[reportPrivateUsage]
```

In v2, the lowlevel `Server` no longer has decorator methods (handlers are constructor-only), so the equivalent workaround is `_add_request_handler`:

**After (v2):**

```python
from mcp.server import ServerRequestContext
from mcp.types import EmptyResult, SetLevelRequestParams, SubscribeRequestParams


async def handle_set_logging_level(ctx: ServerRequestContext, params: SetLevelRequestParams) -> EmptyResult:
    ...
    return EmptyResult()


async def handle_subscribe(ctx: ServerRequestContext, params: SubscribeRequestParams) -> EmptyResult:
    ...
    return EmptyResult()


mcp._lowlevel_server._add_request_handler("logging/setLevel", handle_set_logging_level)  # pyright: ignore[reportPrivateUsage]
mcp._lowlevel_server._add_request_handler("resources/subscribe", handle_subscribe)  # pyright: ignore[reportPrivateUsage]
```

This is a private API and may change. A public way to register these handlers on `MCPServer` is planned; until then, use this workaround or use the lowlevel `Server` directly.

### `MCPServer`'s `Context` logging: `message` renamed to `data`, `extra` removed

On the high-level `Context` object (`mcp.server.mcpserver.Context`), `log()`, `.debug()`, `.info()`, `.warning()`, and `.error()` now take `data: Any` instead of `message: str`, matching the MCP spec's `LoggingMessageNotificationParams.data` field which allows any JSON-serializable value. The `extra` parameter has been removed — pass structured data directly as `data`.

The lowlevel `ServerSession.send_log_message(data: Any)` already accepted arbitrary data and is unchanged.

`Context.log()` also now accepts all eight RFC-5424 log levels (`debug`, `info`, `notice`, `warning`, `error`, `critical`, `alert`, `emergency`) via the `LoggingLevel` type, not just the four it previously allowed.

```python
# Before
await ctx.info("Connection failed", extra={"host": "localhost", "port": 5432})
await ctx.log(level="info", message="hello")

# After
await ctx.info({"message": "Connection failed", "host": "localhost", "port": 5432})
await ctx.log(level="info", data="hello")
```

Positional calls (`await ctx.info("hello")`) are unaffected.

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

The same applies when constructing values — the wrapper call is no longer needed:

**Before (v1):**

```python
await session.send_notification(ClientNotification(InitializedNotification()))
await session.send_request(ClientRequest(PingRequest()), EmptyResult)
```

**After (v2):**

```python
await session.send_notification(InitializedNotification())
await session.send_request(PingRequest(), EmptyResult)
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

### `RequestContext` type parameters simplified

The `mcp.shared.context` module has been removed. `RequestContext` is now split into `ClientRequestContext` (in `mcp.client.context`) and `ServerRequestContext` (in `mcp.server.context`).

The `RequestContext` class has been split to separate shared fields from server-specific fields. The shared `RequestContext` now only takes 1 type parameter (the session type) instead of 3.

**`RequestContext` changes:**

- Type parameters reduced from `RequestContext[SessionT, LifespanContextT, RequestT]` to `RequestContext[SessionT]`
- Server-specific fields (`lifespan_context`, `experimental`, `request`, `close_sse_stream`, `close_standalone_sse_stream`) moved to new `ServerRequestContext` class in `mcp.server.context`

**Before (v1):**

```python
from mcp.client.session import ClientSession
from mcp.shared.context import RequestContext, LifespanContextT, RequestT

# RequestContext with 3 type parameters
ctx: RequestContext[ClientSession, LifespanContextT, RequestT]
```

**After (v2):**

```python
from mcp.client.context import ClientRequestContext
from mcp.server.context import ServerRequestContext, LifespanContextT, RequestT

# For client-side context (sampling, elicitation, list_roots callbacks)
ctx: ClientRequestContext

# For server-specific context with lifespan and request types
server_ctx: ServerRequestContext[LifespanContextT, RequestT]
```

The high-level `Context` class (injected into `@mcp.tool()` etc.) similarly dropped its `ServerSessionT` parameter: `Context[ServerSessionT, LifespanContextT, RequestT]` → `Context[LifespanContextT, RequestT]`. Both remaining parameters have defaults, so bare `Context` is usually sufficient:

**Before (v1):**

```python
async def my_tool(ctx: Context[ServerSession, None]) -> str: ...
```

**After (v2):**

```python
async def my_tool(ctx: Context) -> str: ...
# or, with an explicit lifespan type:
async def my_tool(ctx: Context[MyLifespanState]) -> str: ...
```

### `ProgressContext` and `progress()` context manager removed

The `mcp.shared.progress` module (`ProgressContext`, `Progress`, and the `progress()` context manager) has been removed. This module had no real-world adoption — all users send progress notifications via `Context.report_progress()` or `session.send_progress_notification()` directly.

**Before (v1):**

```python
from mcp.shared.progress import progress

with progress(ctx, total=100) as p:
    await p.progress(25)
```

**After — use `Context.report_progress()` (recommended):**

```python
@server.tool()
async def my_tool(x: int, ctx: Context) -> str:
    await ctx.report_progress(25, 100)
    return "done"
```

**After — use `session.send_progress_notification()` (low-level):**

```python
await session.send_progress_notification(
    progress_token=progress_token,
    progress=25,
    total=100,
)
```

### `create_connected_server_and_client_session` removed

The `create_connected_server_and_client_session` helper in `mcp.shared.memory` has been removed. Use `mcp.client.Client` instead — it accepts a `Server` or `MCPServer` instance directly and handles the in-memory transport and session setup for you.

**Before (v1):**

```python
from mcp.shared.memory import create_connected_server_and_client_session

async with create_connected_server_and_client_session(server) as session:
    result = await session.call_tool("my_tool", {"x": 1})
```

**After (v2):**

```python
from mcp.client import Client

async with Client(server) as client:
    result = await client.call_tool("my_tool", {"x": 1})
```

`Client` accepts the same callback parameters the old helper did (`sampling_callback`, `list_roots_callback`, `logging_callback`, `message_handler`, `elicitation_callback`, `client_info`) plus `raise_exceptions` to surface server-side errors.

If you need direct access to the underlying `ClientSession` and memory streams (e.g., for low-level transport testing), `create_client_server_memory_streams` is still available in `mcp.shared.memory`:

```python
import anyio
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

async with create_client_server_memory_streams() as (client_streams, server_streams):
    async with anyio.create_task_group() as tg:
        tg.start_soon(lambda: server.run(*server_streams, server.create_initialization_options()))
        async with ClientSession(*client_streams) as session:
            await session.initialize()
            ...
        tg.cancel_scope.cancel()
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

### Lowlevel `Server`: type parameter reduced from 2 to 1

The `Server` class previously had two type parameters: `Server[LifespanResultT, RequestT]`. The `RequestT` parameter has been removed — handlers now receive typed params directly rather than a generic request type.

```python
# Before (v1)
from typing import Any

from mcp.server.lowlevel.server import Server

server: Server[dict[str, Any], Any] = Server(...)

# After (v2)
from typing import Any

from mcp.server import Server

server: Server[dict[str, Any]] = Server(...)
```

### Lowlevel `Server`: `request_handlers` and `notification_handlers` attributes removed

The public `server.request_handlers` and `server.notification_handlers` dictionaries have been removed. Handler registration is now done exclusively through constructor `on_*` keyword arguments. There is no public API to register handlers after construction.

```python
# Before (v1) — direct dict access
from mcp.types import ListToolsRequest

if ListToolsRequest in server.request_handlers:
    ...

# After (v2) — no public access to handler dicts
# Use the on_* constructor params to register handlers
server = Server("my-server", on_list_tools=handle_list_tools)
```

If you need to check whether a handler is registered, track this yourself — there is currently no public introspection API.

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
    return ListToolsResult(tools=[Tool(name="my_tool", description="A tool", input_schema={})])


async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=f"Called {params.name}")],
        is_error=False,
    )

server = Server("my-server", on_list_tools=handle_list_tools, on_call_tool=handle_call_tool)
```

**Key differences:**

- Handlers receive `(ctx, params)` instead of the full request object or unpacked arguments. `ctx` is a `ServerRequestContext` with `session`, `lifespan_context`, and `experimental` fields (plus `request_id`, `meta`, etc. for request handlers). `params` is the typed request params object.
- Handlers return the full result type (e.g. `ListToolsResult`) rather than unwrapped values (e.g. `list[Tool]`).
- The automatic `jsonschema` input/output validation that the old `call_tool()` decorator performed has been removed. There is no built-in replacement — if you relied on schema validation in the lowlevel server, you will need to validate inputs yourself in your handler.

**Complete handler reference:**

All handlers receive `ctx: ServerRequestContext` as the first argument. The second argument and return type are:

| v1 decorator | v2 constructor kwarg | `params` type | return type |
|---|---|---|---|
| `@server.list_tools()` | `on_list_tools` | `PaginatedRequestParams \| None` | `ListToolsResult` |
| `@server.call_tool()` | `on_call_tool` | `CallToolRequestParams` | `CallToolResult \| CreateTaskResult` |
| `@server.list_resources()` | `on_list_resources` | `PaginatedRequestParams \| None` | `ListResourcesResult` |
| `@server.list_resource_templates()` | `on_list_resource_templates` | `PaginatedRequestParams \| None` | `ListResourceTemplatesResult` |
| `@server.read_resource()` | `on_read_resource` | `ReadResourceRequestParams` | `ReadResourceResult` |
| `@server.subscribe_resource()` | `on_subscribe_resource` | `SubscribeRequestParams` | `EmptyResult` |
| `@server.unsubscribe_resource()` | `on_unsubscribe_resource` | `UnsubscribeRequestParams` | `EmptyResult` |
| `@server.list_prompts()` | `on_list_prompts` | `PaginatedRequestParams \| None` | `ListPromptsResult` |
| `@server.get_prompt()` | `on_get_prompt` | `GetPromptRequestParams` | `GetPromptResult` |
| `@server.completion()` | `on_completion` | `CompleteRequestParams` | `CompleteResult` |
| `@server.set_logging_level()` | `on_set_logging_level` | `SetLevelRequestParams` | `EmptyResult` |
| — | `on_ping` | `RequestParams \| None` | `EmptyResult` |
| `@server.progress_notification()` | `on_progress` | `ProgressNotificationParams` | `None` |
| — | `on_roots_list_changed` | `NotificationParams \| None` | `None` |

All `params` and return types are importable from `mcp.types`.

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

The old decorator auto-wrapped `Iterable[ReadResourceContents]` (and the deprecated `str`/`bytes` shorthand) into `TextResourceContents`/`BlobResourceContents`, handling base64 encoding and mime-type defaulting:

```python
# Before (v1) — Iterable[ReadResourceContents] auto-wrapped
from mcp.server.lowlevel.helper_types import ReadResourceContents

@server.read_resource()
async def handle(uri: AnyUrl) -> Iterable[ReadResourceContents]:
    return [ReadResourceContents(content="file contents", mime_type="text/plain")]

# Before (v1) — str/bytes shorthand (already deprecated in v1)
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

The `server.request_context` property has been removed. Request context is now passed directly to handlers as the first argument (`ctx`). The `request_ctx` module-level contextvar has been removed entirely.

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
server.experimental.enable_tasks()

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

### Lowlevel `Server`: `subscribe` capability now correctly reported

Previously, the lowlevel `Server` hardcoded `subscribe=False` in resource capabilities even when a `subscribe_resource()` handler was registered. The `subscribe` capability is now dynamically set to `True` when an `on_subscribe_resource` handler is provided. Clients that previously didn't see `subscribe: true` in capabilities will now see it when a handler is registered, which may change client behavior.

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
    _meta={"my_custom_key": "value", "another": 123},  # OK
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

1. Check the [API Reference](api/mcp/index.md) for updated method signatures
2. Review the [examples](https://github.com/modelcontextprotocol/python-sdk/tree/main/examples) for updated usage patterns
3. Open an issue on [GitHub](https://github.com/modelcontextprotocol/python-sdk/issues) if you find a bug or need further assistance
