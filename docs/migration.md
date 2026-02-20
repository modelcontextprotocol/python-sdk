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
`

**In request context handlers:**

```python
# Before (v1)
@server.call_tool()
async def handle_tool(name: str, arguments: dict) -> list[TextContent]:
    ctx = server.request_context
    if ctx.meta and ctx.meta.progress_token:
        await ctx.session.send_progress_notification(ctx.meta.progress_token, 0.5, 100)

# After (v2)
@server.call_tool()
async def handle_tool(name: str, arguments: dict) -> list[TextContent]:
    ctx = server.request_context
    if ctx.meta and "progress_token" in ctx.meta:
        await ctx.session.send_progress_notification(ctx.meta["progress_token"], 0.5, 100)
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

### Transport Abstractions Refactored

The session hierarchy has been refactored to support pluggable transport implementations. This introduces several breaking changes:

#### `ClientRequestContext` type changed

`ClientRequestContext` is now `RequestContext[BaseClientSession]` instead of `RequestContext[ClientSession]`. This means callbacks receive the more general `BaseClientSession` type, which may not have all methods available on `ClientSession`.

**Before:**

```python
from mcp.client.context import ClientRequestContext
from mcp.client.session import ClientSession

async def my_callback(context: ClientRequestContext) -> None:
    # Could access ClientSession-specific methods
    caps = context.session.get_server_capabilities()
```

**After:**

```python
from mcp.client.context import ClientRequestContext
from mcp.client.session import ClientSession

async def my_callback(context: ClientRequestContext) -> None:
    # context.session is BaseClientSession - narrow the type if needed
    if isinstance(context.session, ClientSession):
        caps = context.session.get_server_capabilities()
```

#### Callback protocols are now generic

`sampling_callback`, `elicitation_callback`, and `list_roots_callback` protocols now require explicit type parameters.

**Before:**

```python
from mcp.client.session import SamplingFnT

async def my_sampling(context, params) -> CreateMessageResult:
    ...

# Type inferred as SamplingFnT
session = ClientSession(..., sampling_callback=my_sampling)
```

**After:**

```python
from mcp.client.session import SamplingFnT, ClientSession

async def my_sampling(
    context: RequestContext[ClientSession],
    params: CreateMessageRequestParams
) -> CreateMessageResult:
    ...

# Explicit type annotation recommended
my_sampling_typed: SamplingFnT[ClientSession] = my_sampling
session = ClientSession(..., sampling_callback=my_sampling_typed)
```

#### `SessionT` renamed to `SessionT_co`

In `mcp.shared._context` and `mcp.shared.progress`, the `SessionT` TypeVar has been renamed to `SessionT_co` to follow naming conventions for covariant type variables.

**Before:**

```python
from mcp.shared._context import SessionT
```

**After:**

```python
from mcp.shared._context import SessionT_co
```

#### New `AbstractBaseSession` structural interface

The session hierarchy now uses a new **runtime-checkable Protocol** called `AbstractBaseSession` to define the shared contract for all MCP sessions. This protocol enables structural subtyping, allowing different transport implementations to be used interchangeably without requiring rigid inheritance.

Key characteristics of `AbstractBaseSession`:
1.  **Pure Interface**: It is a structural protocol with no implementation state or `__init__` method.
2.  **Simplified Type Parameters**: It takes two parameters: `AbstractBaseSession[SendRequestT, SendNotificationT]`. Contravariant variance is used for these parameters to ensure that sessions can be used safely in generic contexts (like `RequestContext`).
3.  **BaseSession Implementation**: The concrete implementation logic (state management, response routing) is provided by the `BaseSession` class, which satisfies the protocol.

**Before:**

```python
from mcp.shared.session import AbstractBaseSession

class MySession(AbstractBaseSession[MyMessage, ...]):
    def __init__(self):
        super().__init__()  # Would set up _response_streams, _task_group
```

**After:**

```python
from mcp.shared.session import AbstractBaseSession

class MySession(AbstractBaseSession[...]):
    def __init__(self):
        # Manage your own state - no super().__init__() to call
        self._my_state = {}
```

#### `SendRequestT` changed to contravariant

The `SendRequestT` TypeVar is now defined as **contravariant** to support its use in the `AbstractBaseSession` Protocol.

**Before:**

```python
SendRequestT = TypeVar("SendRequestT", ClientRequest, ServerRequest)
```

**After:**

```python
SendRequestT = TypeVar("SendRequestT", ClientRequest, ServerRequest, contravariant=True)
```

#### `SendNotificationT` changed to contravariant

The `SendNotificationT` TypeVar is now defined as **contravariant** to support its use in the `AbstractBaseSession` Protocol.

**Before:**

```python
SendNotificationT = TypeVar("SendNotificationT", ClientNotification, ServerNotification)
```

**After:**

```python
SendNotificationT = TypeVar(
    "SendNotificationT", ClientNotification, ServerNotification, contravariant=True
)
```

#### `ReceiveResultT` changed to covariant

The `ReceiveResultT` TypeVar is now defined as **covariant** to support its use in the `AbstractBaseSession` Protocol.

**Before:**

```python
ReceiveResultT = TypeVar("ReceiveResultT", bound=BaseModel)
```

**After:**

```python
ReceiveResultT = TypeVar("ReceiveResultT", bound=BaseModel, covariant=True)
```

#### `BaseClientSession` is now a Protocol

`BaseClientSession` is now a `typing.Protocol` (structural subtyping) instead of an abstract base class. It no longer inherits from `AbstractBaseSession` and requires no inheritance to satisfy.

**Before:**

```python
from mcp.client.base_client_session import BaseClientSession

class MyClientSession(BaseClientSession):
    async def initialize(self) -> InitializeResult:
        ...
```

**After:**

```python
from mcp.client.base_client_session import BaseClientSession

class MyClientSession:
    # Just implement the methods - no inheritance needed
    async def initialize(self) -> InitializeResult:
        ...

# Verify protocol satisfaction at runtime
assert isinstance(MyClientSession(), BaseClientSession)
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
from mcp.server.lowlevel.server import Server

server = Server("my-server")

# Register handlers...
@server.list_tools()
async def list_tools():
    return [...]

# Create a Starlette app for streamable HTTP
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
