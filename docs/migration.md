# Migration Guide: v1 to v2

This guide covers the breaking changes introduced in v2 of the MCP Python SDK and how to update your code.

Version 2 of the MCP Python SDK introduces several breaking changes to improve the API, align with the MCP specification, and provide better type safety.

## Find your changes

Every section heading below names the API it affects, so searching this page for the symbol your code uses is the fastest route to the change that broke it.

### Changes almost every project hits

| Change | First symptom | Section |
|---|---|---|
| `FastMCP` renamed to `MCPServer` | `ModuleNotFoundError: No module named 'mcp.server.fastmcp'` | [`FastMCP` renamed](#fastmcp-renamed-to-mcpserver) |
| Fields renamed from camelCase to snake_case | `AttributeError: 'Tool' object has no attribute 'inputSchema'` | [snake_case fields](#field-names-changed-from-camelcase-to-snake_case) |
| `mcp.types` moved to the `mcp-types` package | `ModuleNotFoundError: No module named 'mcp.types'` | [`mcp.types` moved](#mcptypes-moved-to-the-mcp-types-package) |
| `McpError` renamed to `MCPError` | `ImportError: cannot import name 'McpError' from 'mcp'` | [`McpError` renamed](#mcperror-renamed-to-mcperror) |
| Resource URIs are `str`, not `AnyUrl` | `AttributeError: 'str' object has no attribute 'host'` | [URI type](#resource-uri-type-changed-from-anyurl-to-str) |
| `streamablehttp_client` removed | `ImportError: cannot import name 'streamablehttp_client'` | [`streamablehttp_client`](#streamablehttp_client-removed) |
| `Client` defaults to `mode='auto'` | servers log an unexpected `server/discover` request | [`mode='auto'`](#client-defaults-to-modeauto) |
| Transport parameters moved off the `MCPServer` constructor | `TypeError: MCPServer.__init__() got an unexpected keyword argument 'port'` | [constructor parameters](#transport-specific-parameters-moved-from-mcpserver-constructor-to-runapp-methods) |
| Sync handlers run on a worker thread | `asyncio.get_running_loop()` in a `def` handler raises `RuntimeError` | [worker threads](#sync-handler-functions-now-run-on-a-worker-thread) |
| Lowlevel decorators replaced with `on_*` constructor params | `AttributeError: 'Server' object has no attribute 'list_tools'` | [`on_*` handlers](#lowlevel-server-decorator-based-handlers-replaced-with-constructor-on_-params) |
| Lowlevel return value wrapping removed | bare list or dict returns fail result validation instead of being wrapped | [wrapping removed](#lowlevel-server-automatic-return-value-wrapping-removed) |
| Lowlevel tool exceptions no longer become `isError: true` results | clients raise a JSON-RPC error instead of seeing the error text | [tool exceptions](#lowlevel-server-tool-handler-exceptions-no-longer-become-calltoolresultis_errortrue) |
| Roots, Sampling, and Logging deprecated (SEP-2577) | `MCPDeprecationWarning` at call sites | [SEP-2577](#roots-sampling-and-logging-methods-deprecated-sep-2577) |

### Find your area

| If you... | Read |
|---|---|
| pin dependencies or use the `mcp` CLI | [Packaging, dependencies, and CLI](#packaging-dependencies-and-cli) |
| import `mcp.types` or touch protocol types (everyone does) | [Types and wire format](#types-and-wire-format) |
| run `FastMCP`/`MCPServer` servers | [MCPServer (formerly FastMCP)](#mcpserver-formerly-fastmcp) |
| use the lowlevel `Server` | [Lowlevel Server](#lowlevel-server), plus [Timeouts take `float` seconds](#timeouts-take-float-seconds-instead-of-timedelta) and [Experimental Tasks support removed](#experimental-tasks-support-removed) under Clients |
| write client code with `Client` or `ClientSession` | [Clients](#clients), plus [`streamablehttp_client` removed](#streamablehttp_client-removed) under Transports |
| use stdio or streamable HTTP directly, or maintain a custom transport | [Transports](#transports) |
| maintain OAuth client auth or a protected server | [OAuth and server auth](#oauth-and-server-auth) |
| relied on lenient handling of off-schema traffic, or assert on exact wire bytes | [Stricter protocol validation and wire behavior](#stricter-protocol-validation-and-wire-behavior) |
| test against in-memory server/client pairs | [Testing utilities](#testing-utilities) |
| use roots, sampling, logging, or client-to-server progress | [Deprecations](#deprecations) |
| operate servers that 2026-era clients will also connect to | [Notes for 2026-era connections](#notes-for-2026-era-connections) |

## Suggested migration order

1. Update your dependency pins and CLI usage: [Packaging, dependencies, and CLI](#packaging-dependencies-and-cli).
2. Apply the mechanical renames and import moves: [Types and wire format](#types-and-wire-format).
3. Port your server surface: [MCPServer (formerly FastMCP)](#mcpserver-formerly-fastmcp) or [Lowlevel Server](#lowlevel-server).
4. Port your client code: [Clients](#clients).
5. Update transport setup and auth: [Transports](#transports) and [OAuth and server auth](#oauth-and-server-auth).
6. Run your tests and check anything that now errors against [Stricter protocol validation and wire behavior](#stricter-protocol-validation-and-wire-behavior) and [Testing utilities](#testing-utilities).
7. Address deprecation warnings: [Deprecations](#deprecations).

## Packaging, dependencies, and CLI

### Dependency floors raised and new required dependencies

v2 raises the minimum versions of several shared dependencies and adds new required ones. A project that pins any of these below the new floor fails dependency resolution before anything installs (uv reports "No solution found when resolving dependencies"; pip fails similarly).

| Dependency | v1.28.1 | v2 | Change |
|---|---|---|---|
| anyio | `>=4.5` | `>=4.9` (Python <3.14) / `>=4.10` (Python >=3.14) | floor raised |
| pydantic | `>=2.11,<3` (Python <3.14) | `>=2.12` | floor raised on Python <3.14; `<3` cap dropped |
| sse-starlette | `>=1.6.1` | `>=3.0.0` | floor raised across two majors |
| typing-extensions | `>=4.9.0` | `>=4.13.0` | floor raised |
| pywin32 (Windows) | `>=310` (Python <3.14) | `>=311` | floor raised on Python <3.14 |
| opentelemetry-api | not a dependency | `>=1.28.0` | new required dependency |
| mcp-types | not a dependency | `==<exact mcp version>` | new, exact-pinned |
| `ws` extra | `websockets>=15.0.1` | removed | see [WebSocket transport removed](#websocket-transport-removed) |

**Before (v1):**

```toml
dependencies = [
    "mcp==1.28.1",
    "sse-starlette>=2,<3",  # own SSE endpoints, pinned to the 2.x API
]
```

**After (v2):**

```toml
dependencies = [
    "mcp>=2,<3",
    "sse-starlette>=3",  # absorb sse-starlette's own 2.x -> 3.x changes
]
```

Relax or bump any conflicting pins when upgrading. sse-starlette jumps two majors, so a project that imports `sse_starlette` itself must also work through that library's own breaking changes to co-install with mcp v2. `opentelemetry-api` is a new hard dependency because every outbound request now carries a `_meta` envelope used for OpenTelemetry trace propagation; see [Every outbound request now carries a `_meta` envelope](#every-outbound-request-now-carries-a-_meta-envelope-opentelemetry-is-on-by-default). `mcp-types` is exact-pinned to the SDK version; nothing in a v1 tree can conflict with it, but do not pin `mcp-types` independently of `mcp`.

### `mcp dev` and `mcp install` pin the spawned environment to your SDK version

Both commands run your server through a fresh `uv run --with ...` environment. In v1 the
`mcp` requirement in that command was unpinned, so the spawned environment resolved to the
newest stable release rather than the version you had installed; with a v2 pre-release
installed, `mcp dev server.py` built a v1 environment that could not import a v2 server.
Both commands now pin the requirement to the version you are running
(`mcp==<installed version>`). Source builds and other unpublished versions, which have
nothing on PyPI to pin to, keep the unpinned form.

## Types and wire format

### `mcp.types` moved to the `mcp-types` package

The protocol wire types now live in a standalone distribution, `mcp-types`, imported as
`mcp_types`. Its only runtime dependencies are `pydantic` and `typing-extensions`, so code
that just needs to (de)serialize MCP traffic can install it without the full SDK. The `mcp` package depends on `mcp-types` and
continues to re-export the type names at the top level, so `from mcp import Tool` is
unchanged. Only the `mcp.types` submodule and `mcp.shared.version` were removed. The
package's API reference is at [`mcp_types`](api/mcp_types/index.md).

**Why:** keeping the wire types in their own package lets tooling and lightweight clients
depend on the protocol schema without pulling in `httpx`, `starlette`, `uvicorn`, and the
rest of the server/transport stack.

**Before (v1):**

```python
from mcp.types import Tool, Resource
from mcp.shared.version import LATEST_PROTOCOL_VERSION
```

**After (v2):**

```python
from mcp_types import Tool, Resource
from mcp_types.version import LATEST_PROTOCOL_VERSION

# Names `mcp` already re-exported at the top level are unchanged:
from mcp import Tool, Resource
```

### Removed type aliases and classes

The following type aliases and classes have been removed from `mcp_types`:

| Removed | Replacement |
|---------|-------------|
| `Content` | `ContentBlock` |
| `ResourceReference` | `ResourceTemplateReference` |
| `Cursor` | Use `str` directly |
| `MethodT` | Internal TypeVar, not intended for public use |
| `RequestParamsT` | Internal TypeVar, not intended for public use |
| `NotificationParamsT` | Internal TypeVar, not intended for public use |
| `AnyFunction` | Use `Callable[..., Any]` directly |
| `ClientRequestType`, `ClientNotificationType`, `ClientResultType`, `ServerRequestType`, `ServerNotificationType`, `ServerResultType` | The union is now the bare name: `ClientRequest`, `ClientNotification`, `ClientResult`, `ServerRequest`, `ServerNotification`, `ServerResult` |
| `TaskExecutionMode`, `TASK_FORBIDDEN`, `TASK_OPTIONAL`, `TASK_REQUIRED`, `TASK_STATUS_*` | Use string literals; `TaskStatus` remains as the literal-union type |

**Before (v1):**

```python
from mcp.types import Content, ResourceReference, Cursor
```

**After (v2):**

```python
from mcp_types import ContentBlock, ResourceTemplateReference
# Use `str` instead of `Cursor` for pagination cursors
```

### Field names changed from camelCase to snake_case

All Pydantic model fields in `mcp_types` now use snake_case names for Python attribute access. The JSON wire format is unchanged — traffic the SDK sends still uses camelCase via Pydantic aliases, but your own `model_dump()` calls now need `by_alias=True` to produce it.

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

The models accept both spellings at construction time, so the old camelCase names still work as constructor kwargs (e.g., `Tool(inputSchema={...})` is accepted), but attribute access must use snake_case (`tool.input_schema`).

**If you serialize models yourself, pass `by_alias=True`.** In v1, `model_dump()` produced wire-format camelCase keys because the fields themselves were camelCase. In v2 the same call emits snake_case keys (`input_schema`, not `inputSchema`), which peers and other MCP implementations will not recognize. No error is raised; the output is silently in the wrong shape.

```python
tool.model_dump()                                # {"name": ..., "input_schema": ...}
tool.model_dump(by_alias=True, mode="json")      # {"name": ..., "inputSchema": ...}  (wire format)
```

Parsing is unaffected: `model_validate()` accepts both camelCase wire JSON and snake_case dumps.

### Extra fields on MCP types are no longer preserved

In v1, MCP protocol types were configured with `extra="allow"`: unknown fields passed to a constructor or received from a peer were kept on the model and re-serialized on output.

In v2, MCP types silently ignore extra fields. Unknown constructor keyword arguments and unknown keys in wire data are dropped during validation — no error is raised, and the values do not round-trip:

```python
from mcp_types import CallToolRequestParams

params = CallToolRequestParams(
    name="my_tool",
    arguments={},
    unknown_field="value",  # silently ignored, not stored
)
"unknown_field" in params.model_dump()  # False

# _meta remains the supported place for custom data, per the MCP spec
params = CallToolRequestParams(
    name="my_tool",
    arguments={},
    _meta={"my_custom_key": "value", "another": 123},  # OK, preserved
)
```

If you relied on extra fields round-tripping through MCP types, move that data into `_meta`.

### Resource URI type changed from `AnyUrl` to `str`

The `uri` field on resource-related types now uses `str` instead of Pydantic's `AnyUrl`. This aligns with the [MCP specification schema](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2025-11-25/schema.ts) which defines URIs as plain strings (`uri: string`) without strict URL validation. This change allows relative paths like `users/me` that were previously rejected.

**Before (v1):**

```python
from pydantic import AnyUrl
from mcp.types import Resource

# uri was typed as AnyUrl; relative paths were rejected
resource = Resource(name="test", uri=AnyUrl("users/me"))  # Would fail validation
```

**After (v2):**

```python
from mcp_types import Resource

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

- `Resource.uri` (and subclass `ResourceLink`)
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

URI values you read back are also plain strings now. In v1, fields like `Resource.uri` and `ResourceContents.uri` were `AnyUrl` objects, so attribute access such as `uri.scheme` or `uri.host` worked; in v2 that code raises `AttributeError`. Use `urllib.parse` if you need to parse them. Note that v1 also normalized URIs during validation (for example `https://example.com` became `https://example.com/`), while v2 preserves the string exactly as given, so URIs sent on the wire may differ byte-for-byte from what v1 sent.

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
from mcp_types import client_request_adapter, server_notification_adapter

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

All adapters are exported from `mcp_types`.

### `RequestParams.Meta` replaced with `RequestParamsMeta` TypedDict

The nested `RequestParams.Meta` Pydantic model class has been replaced with a top-level `RequestParamsMeta` TypedDict. This affects the `ctx.meta` field in request handlers and any code that imports or references this type.

**Key changes:**

- `RequestParams.Meta` (Pydantic model) → `RequestParamsMeta` (TypedDict)
- Attribute access (`meta.progressToken`) → Dictionary access (`meta.get("progress_token")`)
- The `progressToken: ProgressToken | None = None` field is now the `progress_token: NotRequired[ProgressToken]` key

**In request context handlers:**

```python
# Before (v1)
@server.call_tool()
async def handle_tool(name: str, arguments: dict) -> list[TextContent]:
    ctx = server.request_context
    if ctx.meta and ctx.meta.progressToken:
        await ctx.session.send_progress_notification(ctx.meta.progressToken, 0.5, 100)

# After (v2)
async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    if ctx.meta and "progress_token" in ctx.meta:
        await ctx.session.send_progress_notification(ctx.meta["progress_token"], 0.5, 100)
    ...

server = Server("my-server", on_call_tool=handle_call_tool)
```

The nested `NotificationParams.Meta` class is gone as well. Notification `_meta` is
now a plain `dict[str, Any]`: pass a dict when constructing params
(`ProgressNotificationParams(progress_token=..., progress=0.5, _meta={"traceparent": ...})`)
and read extras with dictionary access (`params.meta["traceparent"]`) instead of
attribute access. The JSON wire format is unchanged.

### `SUPPORTED_PROTOCOL_VERSIONS` deprecated; `LATEST_PROTOCOL_VERSION` changed meaning

`SUPPORTED_PROTOCOL_VERSIONS` is deprecated — it's now the union of `HANDSHAKE_PROTOCOL_VERSIONS` (initialize-handshake versions) and `MODERN_PROTOCOL_VERSIONS` (per-request-envelope versions). If you were using it to mean "versions the initialize handshake accepts", switch to `HANDSHAKE_PROTOCOL_VERSIONS`. Named scalars derived from these tuples are now exported alongside them — `LATEST_HANDSHAKE_VERSION`, `LATEST_MODERN_VERSION`, `OLDEST_SUPPORTED_VERSION` — so prefer those over indexing the tuples directly. All of these live in `mcp_types.version` (previously `mcp.shared.version`): `from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS`.

`LATEST_PROTOCOL_VERSION` also changed value and meaning. In v1 it was `"2025-11-25"`, the version the client offered during initialization. In v2 it is the newest revision the SDK speaks in any era, currently `"2026-07-28"`, which the initialize handshake cannot negotiate. If you offered it in a hand-built `initialize` request or compared the negotiated version against it, use `LATEST_HANDSHAKE_VERSION` instead. These tuples really are tuples now (`SUPPORTED_PROTOCOL_VERSIONS` was a `list` in v1), so list-only operations such as concatenating with a list raise `TypeError`.

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
from mcp_types import INVALID_REQUEST

raise MCPError(INVALID_REQUEST, "bad input")
# or, if you already have an ErrorData:
raise MCPError.from_error_data(error_data)
```

## MCPServer (formerly FastMCP)

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

`Context` is the type annotation for the `ctx` parameter injected into tools, resources, and prompts (see [`get_context()` removed](#mcpserverget_context-removed) below). The `ctx.fastmcp` property is now `ctx.mcp_server`.

All submodules under `mcp.server.fastmcp.*` are now under `mcp.server.mcpserver.*` with the same structure. Common imports:

- `Image`, `Audio` — from `mcp.server.mcpserver` (or `.utilities.types`)
- `UserMessage`, `AssistantMessage` — from `mcp.server.mcpserver.prompts.base`
- `ToolError`, `ResourceError` — from `mcp.server.mcpserver.exceptions`
- `MCPServerError` (renamed from `FastMCPError`) — from `mcp.server.mcpserver.exceptions`

### Default server name changed from `FastMCP` to `mcp-server`

A server constructed without a name now defaults to `mcp-server` instead of `FastMCP`. This is the name reported to clients as `serverInfo.name` in the initialize result, so it is visible in client UIs, logs, and monitoring. Nothing raises when this changes; the migrated server simply reports a different identity.

**Before (v1):**

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP()  # serverInfo.name == "FastMCP"
```

**After (v2):**

```python
from mcp.server.mcpserver import MCPServer

mcp = MCPServer()  # serverInfo.name == "mcp-server"
```

If test suites assert on the initialize result, or anything keys configuration or allow-lists off `serverInfo.name`, pass a name explicitly: `MCPServer("FastMCP")` preserves the old value, though a real name for your server is better.

### `MCPServer` constructor: `title`, `description`, and `version` added to the positional parameters

The constructor's positional parameter order changed. v2 inserts `title` and `description` before `instructions`, and `version` after `icons`, so the order is now `name`, `title`, `description`, `instructions`, `website_url`, `icons`, `version`. In v1 the order was `name`, `instructions`, `website_url`, `icons`.

A v1 call that passed `instructions` positionally still runs without error on v2, because both slots are `str | None`. The text silently lands in `title` instead: the server sends it as `serverInfo.title` and stops sending `instructions` in the initialize result, which clients feed to the model.

**Before (v1):**

```python
from mcp.server.fastmcp import FastMCP

# Second positional parameter is instructions
mcp = FastMCP("Demo", "You answer questions about the weather.")
```

**After (v2):**

```python
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("Demo", instructions="You answer questions about the weather.")
```

Keep `name` positional and pass everything else by keyword.

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

### Streamable HTTP: lifespan now entered once at manager startup

When serving streamable HTTP (stateful or `stateless_http=True`), the server's `lifespan` context manager is now entered once when `StreamableHTTPSessionManager.run()` starts, and the resulting state is shared across all sessions and requests. Previously each session (stateful) or each request (stateless) entered and exited `lifespan` independently.

Lifespans that set up process-wide state (connection pools, caches, background tasks) are unaffected — they now run once instead of per session/request. If your lifespan was acquiring per-connection resources, move that acquisition into the handler body; per-connection cleanup belongs on the connection's `exit_stack` (a public way to reach it from high-level `@mcp.tool()` handlers is planned).

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

### Sync handler functions now run on a worker thread

In v1, a synchronous (`def`) tool, resource, or prompt function was called inline on the event
loop, so a body that blocked (an HTTP call with a sync client, `time.sleep()`, heavy
computation) stalled every other in-flight request on the server. In v2 the SDK runs
synchronous handler functions in a worker thread via `anyio.to_thread.run_sync()`;
`async def` handlers are unchanged. Resolver functions (`Resolve(...)`) follow the same rule.

Most servers simply gain concurrency. Port with care if a synchronous handler relied on
running on the event-loop thread:

- Thread-affine state (thread locals shared with startup code, non-thread-safe objects that
  were only ever touched from the event loop's thread) is now touched from a worker thread.
- `asyncio.get_running_loop()` inside a synchronous handler body raises `RuntimeError`; there
  is no running loop in a worker thread.
- Synchronous handlers can run concurrently with each other, up to anyio's default
  worker-thread limit.

Declare the handler `async def` to keep it on the event loop.

### `MCPServer.call_tool()` returns `CallToolResult`

`MCPServer.call_tool()` now returns a `CallToolResult` (or an
`InputRequiredResult` when a multi-round tool requests further input). It previously
advertised `Sequence[ContentBlock] | dict[str, Any]` and leaked the internal
conversion shapes (a bare content sequence or a `(content, structured_content)`
tuple), forcing callers to re-assemble a `CallToolResult` themselves.

If you call `MCPServer.call_tool()` directly, read `.content` and
`.structured_content` off the returned `CallToolResult` instead of branching on
the result type.

### `MCPServer.get_prompt()` and `read_resource()` may return `InputRequiredResult`

Like `call_tool()` above, `MCPServer.get_prompt()` now returns
`GetPromptResult | InputRequiredResult` and `MCPServer.read_resource()` returns
`Iterable[ReadResourceContents] | InputRequiredResult`: at 2026-07-28 an
`@mcp.prompt()` function or an `@mcp.resource()` template function may answer
with an `InputRequiredResult` to request client input first (see
[Multi-round-trip requests](handlers/multi-round-trip.md)). If you call these
methods directly, narrow with `isinstance` (or
`assert not isinstance(result, InputRequiredResult)` when your prompt and
resource functions never return one). `Prompt.render()` and
`ResourceTemplate.create_resource()` carry the same union.

`ctx.read_resource()` inside a handler is unchanged: it still returns content,
and raises `RuntimeError` if the resource requests input.

### `MCPServer.call_tool()`, `read_resource()`, `get_prompt()` now accept a `context` parameter

`MCPServer.call_tool()`, `MCPServer.read_resource()`, and `MCPServer.get_prompt()` now accept an optional `context: Context | None = None` parameter. The framework passes this automatically during normal request handling. If you call these methods directly and omit `context`, a Context with no active request is constructed for you — tools that don't use `ctx` work normally, but any attempt to use `ctx.session`, `ctx.request_id`, etc. will raise.

The internal layers (`ToolManager.call_tool`, `Tool.run`, `Prompt.render`, `ResourceTemplate.create_resource`, etc.) now require `context` as a positional argument.

### Resolver-routed requests require the client capability on every protocol version

A v1 server could send elicitation, sampling, and roots requests to clients
that never declared the matching capability; only tools-bearing sampling was
checked. In v2 the `Resolve(...)` markers (`Elicit`, `Sample`, `ListRoots`)
enforce the spec's egress rule: an undeclared capability (form-mode `elicitation`,
`sampling`, or `roots`, plus `sampling.tools` when the request carries `tools`
or `tool_choice`) fails the call with a `-32021`
`MISSING_REQUIRED_CLIENT_CAPABILITY` JSON-RPC error instead of sending a
request the client cannot handle. This applies on 2025-11-25 sessions with a
live back-channel too; a session with no back-channel keeps failing with its
no-back-channel error. To migrate, declare the capability: the SDK client
declares `elicitation`, `sampling`, and `roots` when the matching callback is
set, and `sampling.tools` needs an explicit
`Client(sampling_capabilities=SamplingCapability(tools=...))`. Direct
`ctx.elicit()` and `ctx.session.*` calls outside resolvers keep their previous
behavior, including the pre-existing tools check on `create_message`.

### `MCPError` raised from an `@mcp.tool()` handler now surfaces as a JSON-RPC error

Raising `MCPError` (or any subclass) inside an `@mcp.tool()` handler now
produces a top-level JSON-RPC error response with the raised `code`, `message`,
and `data` intact. Previously the tool wrapper caught it like any other
exception and returned `CallToolResult(isError=True)`, which discarded the
error code and structured `data`. The one exception was
`UrlElicitationRequiredError`, which v1 already re-raised as a JSON-RPC error;
its behavior is unchanged.

`MCPError` carries `ErrorData` and is the SDK's protocol-error type — raise it
when the request itself should be rejected (missing client capability,
elicitation required, invalid parameters). For tool *execution* failures the
calling LLM should see and react to, raise any other exception or return
`CallToolResult(is_error=True, ...)` directly; that path is unchanged.

### Resource not found returns `-32602` and resource lookups raise typed exceptions (SEP-2164)

Reading a missing resource now returns JSON-RPC error code `-32602` (invalid params) with the requested URI in `error.data` (`{"uri": ...}`), per [SEP-2164](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2164). Previously the server returned code `0` with no `data`. Clients can now reliably distinguish not-found from other errors; a template handler that raises `ResourceNotFoundError` (from `mcp.server.mcpserver.exceptions`) produces this same response.

The underlying lookups now raise typed exceptions instead of `ValueError`. `ResourceManager.get_resource()` raises `ResourceNotFoundError` when no resource or template matches the URI, and `ResourceTemplate.create_resource()` raises `ResourceError` when the template function fails. Neither subclasses `ValueError`, so callers catching `ValueError` should switch to `ResourceNotFoundError` / `ResourceError` (both importable from `mcp.server.mcpserver.exceptions`; `ResourceNotFoundError` subclasses `ResourceError`).

### Resource templates: matching behavior changes

Resource template matching has been rewritten with [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570) support.
Several behaviors have changed:

**Path-safety checks applied by default.** Extracted parameter values
containing `..` as a path component, a null byte, or looking like an
absolute path (`/etc/passwd`, `C:\Windows`) now cause the read to
fail — the client receives an "Unknown resource" error and template
iteration stops, so a strict template's rejection does not fall
through to a later permissive template. This is checked on the
decoded value, so `..%2Fetc`, `%2E%2E`, and `%00` are caught too.
Note that `..` is only flagged as a standalone path component, so
values like `v1.0..v2.0` or `HEAD~3..HEAD` are unaffected.

If a parameter legitimately needs to receive absolute paths or
traversal sequences, exempt it:

```python
from mcp.server.mcpserver import ResourceSecurity

@mcp.resource(
    "inspect://file/{+target}",
    security=ResourceSecurity(exempt_params={"target"}),
)
def inspect_file(target: str) -> str: ...
```

**Template literals and structural delimiters match exactly.** The
previous matcher built a regex without escaping, so `.` matched any
character and simple `{var}` swallowed `?`, `#`, `&`, and `,`. Now
`data://v1.0/{id}` no longer matches `data://v1X0/42`, and
`api://{id}` no longer matches `api://foo?x=1` — use `api://{id}{?x}`
to capture the query parameter.

**`{var}` now matches an empty value.** A simple expression captures
zero or more characters, so `tickets://{ticket_id}` now matches
`tickets://` with `ticket_id=""` (v1.x's `[^/]+` regex required at
least one). This makes `match` round-trip `expand` for empty values — RFC 6570
expands an empty string to nothing — but handlers that assumed a
non-empty value should validate it explicitly.

**Template syntax errors surface at decoration time.** Unclosed
braces, duplicate variable names, and unsupported syntax raise
`InvalidUriTemplate` when the decorator runs rather than `re.error`
on first match. Two variables with no literal between them are also
rejected — matching cannot tell where one ends and the next begins —
so `{name}{+path}` raises. Write `{name}/{+path}`, or use an operator
that emits its own delimiter: `{+path}{.ext}` is fine because the `.`
operator contributes a literal `.` between the two. A handler
parameter bound to a query variable in the template's trailing
`{?...}`/`{&...}` run — the variables `match()` treats as optional,
listed by `UriTemplate.query_variable_names` — must declare a Python
default: a client may omit those, so a handler that requires one now
raises `ValueError` when the decorator runs instead of failing on the
first request that leaves it out. (A `{&...}` expression with no
preceding `{?...}` is not in that run: it is matched strictly, may
not be omitted, and needs no default.)

**Static URIs with Context-only handlers now error.** A non-template
URI paired with a handler that takes only a `Context` parameter
previously registered but was silently unreachable (the resource
could never be read). This now raises `ValueError` at decoration time.
Context injection for static resources is not supported — use a
template with at least one variable or access context through other
means.

See [URI templates](servers/uri-templates.md) for the full template syntax,
security configuration, and filesystem safety utilities.

### `MCPServer`'s `Context` logging: `message` renamed to `data`, `extra` removed

On the high-level `Context` object (`mcp.server.mcpserver.Context`), `log()`, `.debug()`, `.info()`, `.warning()`, and `.error()` now take `data: Any` instead of `message: str`, matching the MCP spec's `LoggingMessageNotificationParams.data` field which allows any JSON-serializable value. The `extra` parameter has been removed from the convenience-method signatures. Note that `extra` never worked at runtime in v1 (the kwargs were forwarded to `log()`, which did not accept them, raising `TypeError`), so this only affects code that type-checked but never exercised that path. Pass structured data directly as `data`.

The lowlevel `ServerSession.send_log_message(data: Any)` already accepted arbitrary data and is unchanged.

`Context.log()` also now accepts all eight [RFC 5424](https://datatracker.ietf.org/doc/html/rfc5424) log levels (`debug`, `info`, `notice`, `warning`, `error`, `critical`, `alert`, `emergency`) via the `LoggingLevel` type, not just the four it previously allowed.

```python
# Before
await ctx.info("Connection failed", extra={"host": "localhost", "port": 5432})  # extra= type-checked but raised TypeError at runtime in v1
await ctx.log(level="info", message="hello")

# After
await ctx.info({"message": "Connection failed", "host": "localhost", "port": 5432})
await ctx.log(level="info", data="hello")
```

Positional calls (`await ctx.info("hello")`) are unaffected.

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
@mcp.tool()
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

### `Context.elicit()` schema gate validates the rendered schema

`Context.elicit()` (and `elicit_with_validation()`) now render the schema first and validate each property against the spec's `PrimitiveSchemaDefinition`, raising `TypeError` at the call site for anything outside it. `Optional[T]` fields render as `{"type": ...}` with the field omitted from `required` (previously the non-spec `anyOf` shape). A bare `list[str]` field is rejected because it renders without the required enum items; use `list[Literal[...]]` or `list[str]` with `json_schema_extra` supplying the items. Unions of multiple primitives (e.g. `int | str`) and nested models are rejected.

A schema-mismatched *accepted* answer also fails differently: the call now raises `ValueError` with a stable message ("Received an accepted elicitation whose content does not match the requested schema") instead of letting pydantic's `ValidationError` escape with its internals. Code that caught `ValidationError` around `ctx.elicit()` should catch `ValueError` (or rely on the tool's error result).

### `isinstance()` checks against `ElicitationResult` raise `TypeError`

`ElicitationResult` is now a `TypeAliasType` instead of a plain union, so `ElicitationResult[Confirm]` works as an annotation (resolver dependency injection consumes it that way - see [Dependencies](handlers/dependencies.md)). The members are unchanged: `AcceptedElicitation[T] | DeclinedElicitation | CancelledElicitation`.

The one behavioral change: a runtime `isinstance(result, ElicitationResult)` now raises `TypeError`. Check against the member classes directly instead:

```python
result = await ctx.elicit("Proceed?", Confirm)
if isinstance(result, AcceptedElicitation):
    ...  # result.data is a Confirm
```

Narrowing on `result.action` (`"accept"` / `"decline"` / `"cancel"`) is unaffected.

### Registering lowlevel handlers from `MCPServer`

`MCPServer` does not expose public APIs for `subscribe_resource`, `unsubscribe_resource`, or `set_logging_level` handlers. In v1, the workaround was to reach into the private lowlevel server and use its decorator methods:

**Before (v1):**

```python
@mcp._mcp_server.set_logging_level()  # pyright: ignore[reportPrivateUsage]
async def handle_set_logging_level(level: str) -> None:
    ...

mcp._mcp_server.subscribe_resource()(handle_subscribe)  # pyright: ignore[reportPrivateUsage]
```

In v2, the lowlevel `Server` supports arbitrary request handlers directly via `add_request_handler` (the decorator methods are gone; handlers are otherwise constructor-only). From `MCPServer`, access it via `_lowlevel_server`:

**After (v2):**

```python
from mcp.server import ServerRequestContext
from mcp_types import EmptyResult, SetLevelRequestParams, SubscribeRequestParams


async def handle_set_logging_level(ctx: ServerRequestContext, params: SetLevelRequestParams) -> EmptyResult:
    ...
    return EmptyResult()


async def handle_subscribe(ctx: ServerRequestContext, params: SubscribeRequestParams) -> EmptyResult:
    ...
    return EmptyResult()


mcp._lowlevel_server.add_request_handler("logging/setLevel", SetLevelRequestParams, handle_set_logging_level)  # pyright: ignore[reportPrivateUsage]
mcp._lowlevel_server.add_request_handler("resources/subscribe", SubscribeRequestParams, handle_subscribe)  # pyright: ignore[reportPrivateUsage]
```

`_lowlevel_server` is private and may change. A public way to register these handlers on `MCPServer` is planned; until then, use this workaround or use the lowlevel `Server` directly.

## Lowlevel Server

### Lowlevel `Server`: decorator-based handlers replaced with constructor `on_*` params

The lowlevel `Server` class no longer uses decorator methods for handler registration. Instead, handlers are passed as `on_*` keyword arguments to the constructor.

**Before (v1):**

```python
from mcp.server.lowlevel.server import Server
import mcp.types as types

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
from mcp_types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

async def handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[Tool(name="my_tool", description="A tool", input_schema={"type": "object"})])


async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=f"Called {params.name}")],
        is_error=False,
    )

server = Server("my-server", on_list_tools=handle_list_tools, on_call_tool=handle_call_tool)
```

**Key differences:**

- Handlers receive `(ctx, params)` instead of the full request object or unpacked arguments. `ctx` is a `ServerRequestContext` with `session` and `lifespan_context` fields (plus `request_id`, `meta`, etc. for request handlers). `params` is the typed request params object.
- Handlers return the full result type (e.g. `ListToolsResult`) rather than unwrapped values (e.g. `list[Tool]`).
- The automatic `jsonschema` input/output validation that the old `call_tool()` decorator performed has been removed. There is no built-in replacement — if you relied on schema validation in the lowlevel server, you will need to validate inputs yourself in your handler.

**Complete handler reference:**

All handlers receive `ctx: ServerRequestContext` as the first argument. The second argument and return type are:

| v1 decorator | v2 constructor kwarg | `params` type | return type |
|---|---|---|---|
| `@server.list_tools()` | `on_list_tools` | `PaginatedRequestParams \| None` | `ListToolsResult` |
| `@server.call_tool()` | `on_call_tool` | `CallToolRequestParams` | `CallToolResult` |
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

All `params` and return types are importable from `mcp_types`.

**Notification handlers:**

```python
from mcp.server import Server, ServerRequestContext
from mcp_types import ProgressNotificationParams


async def handle_progress(ctx: ServerRequestContext, params: ProgressNotificationParams) -> None:
    print(f"Progress: {params.progress}/{params.total}")

server = Server("my-server", on_progress=handle_progress)
```

Registering `on_progress` emits a deprecation warning because the 2026-07-28 spec deprecates client-to-server progress; see [Client-to-server progress deprecated (2026-07-28)](#client-to-server-progress-deprecated-2026-07-28).

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

### Lowlevel `Server`: tool handler exceptions no longer become `CallToolResult(is_error=True)`

The v1 `@server.call_tool()` decorator caught any exception raised by the handler and returned it to the client as an error-flagged tool result (`isError: true`), so the calling LLM saw the error text as a tool result and could self-correct. In v2, `on_call_tool` is registered with no exception wrapping: a non-`MCPError` exception propagates to the dispatcher and is answered as a top-level JSON-RPC **error response** with `code=0` and `message=str(exc)`. Typical clients (including the SDK's own) raise on a protocol error instead of returning a result, so the error text is no longer LLM-visible. The server also logs a `handler for 'tools/call' raised` traceback that v1 never emitted.

**Before (v1):**

```python
@server.call_tool()
async def call_tool(name: str, arguments: dict):
    raise ValueError("kaboom")  # client receives CallToolResult(isError=True)
```

**After (v2):** catch exceptions in the handler and build the error result yourself:

```python
from mcp.server import Server
from mcp_types import CallToolResult, TextContent


async def handle_call_tool(ctx, params) -> CallToolResult:
    try:
        ...  # tool logic
    except Exception as e:
        return CallToolResult(
            content=[TextContent(type="text", text=str(e))],
            is_error=True,
        )


server = Server("my-server", on_call_tool=handle_call_tool)
```

Raise `MCPError` only when the request itself should be rejected as a protocol error; that path is deliberate in v2. Alternatively, use `MCPServer`, whose `@mcp.tool()` wrapper still converts generic exceptions into `is_error=True` results (see [`MCPError` raised from an `@mcp.tool()` handler now surfaces as a JSON-RPC error](#mcperror-raised-from-an-mcptool-handler-now-surfaces-as-a-json-rpc-error)).

### Lowlevel `Server`: constructor parameters are now keyword-only

All parameters after `name` are now keyword-only. If you were passing `version` or other parameters positionally, use keyword arguments instead:

```python
# Before (v1)
server = Server("my-server", "1.0")

# After (v2)
server = Server("my-server", version="1.0")
```

### Lowlevel `Server`: type parameter reduced from 2 to 1

The `Server` class previously had two type parameters: `Server[LifespanResultT, RequestT]`. The `RequestT` parameter has been removed. In v1 it typed the transport-level request object exposed as `server.request_context.request`, not anything handlers received directly.

```python
# Before (v1)
from typing import Any

from mcp.server import Server

server: Server[dict[str, Any], Any] = Server(...)

# After (v2)
from typing import Any

from mcp.server import Server

server: Server[dict[str, Any]] = Server(...)
```

### Lowlevel `Server`: `request_handlers` and `notification_handlers` attributes removed

The public `server.request_handlers` and `server.notification_handlers` dictionaries have been removed. Handler registration is now done through constructor `on_*` keyword arguments, or through the public `add_request_handler` / `add_notification_handler` methods.

```python
# Before (v1) — direct dict access
from mcp.types import ListToolsRequest

server.request_handlers[ListToolsRequest] = handle_list_tools

if ListToolsRequest in server.request_handlers:
    ...

# After (v2) — no public access to handler dicts
server = Server("my-server", on_list_tools=handle_list_tools)

if server.get_request_handler("tools/list") is not None:
    ...
```

If you need to check whether a handler is registered, use `server.get_request_handler(method)` or `server.get_notification_handler(method)`, which return the registered entry or `None`. Note the lookup key is now the method string (for example `"tools/list"`), not the request type.

### Lowlevel `Server`: `subscribe` capability now correctly reported

Previously, the lowlevel `Server` hardcoded `subscribe=False` in resource capabilities even when a `subscribe_resource()` handler was registered. The `subscribe` capability is now dynamically set to `True` when an `on_subscribe_resource` handler is provided. Clients that previously didn't see `subscribe: true` in capabilities will now see it when a handler is registered, which may change client behavior.

### Lowlevel `Server`: private `_handle_*` dispatch methods removed

`Server._handle_message`, `_handle_request`, and `_handle_notification` have been removed. The receive loop and per-message dispatch now live in `JSONRPCDispatcher` and `ServerRunner`, which `Server.run()` drives internally.

These were private, but some users subclassed `Server` and overrode them to intercept requests. Use middleware instead:

```python
from typing import Any

from mcp.server import Server, ServerRequestContext
from mcp.server.context import CallNext, HandlerResult


async def logging_middleware(ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
    print(f"handling {ctx.method}")
    result = await call_next(ctx)
    print(f"done {ctx.method}")
    return result


server = Server("my-server", on_call_tool=...)
server.middleware.append(logging_middleware)
```

The method and the raw inbound params are `ctx.method` and `ctx.params` (`params` is `None` when the message carries none). Middleware runs before params validation and also wraps unknown methods. To rewrite the method or params before the handler runs, pass an adjusted context through: `await call_next(replace(ctx, params=...))`.

### Lowlevel `Server.run(raise_exceptions=True)`: transport errors no longer re-raised

`raise_exceptions=True` now only governs handler exceptions: an exception raised by an `on_*` handler propagates out of `run()`. The JSON-RPC error response is still written to the client first, regardless of the flag.

Previously it also re-raised exceptions yielded by the transport onto the read stream (e.g. JSON parse errors). Those are now debug-logged and dropped regardless of `raise_exceptions`. If you relied on `run()` exiting on a transport-level parse error, that no longer happens.

### `Server.run()` no longer takes a `stateless` flag

The `stateless: bool` parameter on the lowlevel `Server.run()` has been removed. Stateless serving is now a property of how the connection is constructed (the streamable-HTTP manager builds a born-ready `Connection` per request), not a flag the loop driver inspects.

Server-initiated requests that have no channel to travel on now raise `NoBackChannelError` (an `MCPError` subclass) — the same exception regardless of why the channel is absent. In v1 there was no dedicated exception for this case: the transport silently dropped the outbound message and the awaiting call stalled.

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
from mcp_types import CallToolRequestParams, CallToolResult, TextContent


async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    await ctx.session.send_log_message(level="info", data="Processing...")
    return CallToolResult(
        content=[TextContent(type="text", text="Done")],
        is_error=False,
    )
```

### `RequestContext` type parameters simplified

`RequestContext` has been removed from `mcp.shared.context` (importing it now raises `ImportError`; the module now holds an unrelated internal class). It is split into `ClientRequestContext` (in `mcp.client.context`) and `ServerRequestContext` (in `mcp.server.context`).

**`RequestContext` changes:**

- The `RequestContext[SessionT, LifespanContextT, RequestT]` generic no longer exists; use `ClientRequestContext` or `ServerRequestContext[LifespanContextT, RequestT]`
- Server-specific fields (`lifespan_context`, `request`, `close_sse_stream`, `close_standalone_sse_stream`) moved to new `ServerRequestContext` class in `mcp.server.context`

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

`ServerRequestContext` is a standalone dataclass rather than a specialization of a shared base class. It carries the same fields (`session`, `request_id`, `meta`, `lifespan_context`, `request`, `close_sse_stream`, `close_standalone_sse_stream`) plus new `protocol_version: str`, `method: str`, and raw `params: Mapping[str, Any] | None` fields, so handler code is mostly unaffected, but `isinstance(ctx, RequestContext)` checks and `RequestContext[ServerSession]` annotations need updating to `ServerRequestContext`.

One field is newly optional: `request_id` is now `RequestId | None` (in v1 it was always a `RequestId`). The same context class is passed to notification handlers, where `request_id` is `None`, so code that forwards `ctx.request_id` as a definite `RequestId` needs a `None` check to satisfy type checkers.

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

### `ServerSession` is now a thin proxy (no longer a `BaseSession`)

`ServerSession` no longer subclasses `BaseSession`. It is now a small per-request proxy that exposes `send_request`, `send_notification`, the typed convenience helpers (`create_message`, `elicit_form`, `send_log_message`, `send_tool_list_changed`, ...), `client_params`, `protocol_version`, and `check_client_capability`. The receive loop, `initialize` handling, and per-request task isolation that previously lived in `ServerSession` have moved to `JSONRPCDispatcher` and `ServerRunner`.

`ServerSession` is normally constructed for you by `Server.run()` and reached via `ctx.session` in handlers, so most servers are unaffected. If you were constructing or subclassing it directly:

**Constructor change:**

```python
# Before (v1)
session = ServerSession(read_stream, write_stream, init_options, stateless=False)

# After (v2)
session = ServerSession(request_outbound, connection)
# where `request_outbound` is a DispatchContext and `connection` is a Connection
```

In practice, replace direct `ServerSession` use with `Server.run(read_stream, write_stream, init_options)` and let the framework wire it up.

**Removed from `mcp.server.session`:**

- `InitializationState` enum and `ServerSession._initialization_state` — initialization tracking is now on `Connection` (`connection.initialized` is an `anyio.Event`, `connection.client_params` holds the init params).
- `ServerRequestResponder` type alias.
- `ServerSession.incoming_messages` stream — there is no longer a public stream of inbound messages to iterate. Register handlers via the `on_*` constructor params (or `add_request_handler`) and use `Server.middleware` to observe every inbound request and notification (`initialize`, unknown methods, validation failures, and `notifications/initialized` included).
- `ServerSession.__aenter__` / `__aexit__` — `ServerSession` is no longer an async context manager.
- The private `_receive_loop`, `_received_request`, `_received_notification`, and `_handle_incoming` overrides — there is nothing to override on `ServerSession` anymore. To intercept inbound messages, use `Server.middleware` (see [Lowlevel `Server`: private `_handle_*` dispatch methods removed](#lowlevel-server-private-_handle_-dispatch-methods-removed)).

### `ServerSession.elicit()` and `elicit_form()` take `requested_schema`, not `requestedSchema`

The schema parameter of `ServerSession.elicit()` and `ServerSession.elicit_form()` was renamed from `requestedSchema` to `requested_schema`. This is a plain method parameter, so the `populate_by_name` alias support that keeps camelCase field names working on Pydantic models does not apply here. Keyword callers raise on every call, before any wire traffic (nothing fails at import; the client sees a tool error):

```text
TypeError: ServerSession.elicit_form() got an unexpected keyword argument 'requestedSchema'. Did you mean 'requested_schema'?
```

**Before (v1):**

```python
result = await ctx.session.elicit_form(
    message="Your name?",
    requestedSchema={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
)
```

**After (v2):**

```python
result = await ctx.session.elicit_form(
    message="Your name?",
    requested_schema={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
)
```

Positional callers (`session.elicit_form(message, schema)`) are unaffected. `elicit_url()` already used snake_case parameters in v1; only `elicit()` and `elicit_form()` changed.

## Clients

### `Client` defaults to `mode='auto'`

In v1, connecting to a server always performed the `initialize` handshake. In v2, `Client` defaults to `mode='auto'`: on enter it probes `server/discover` and, if the server doesn't support it, falls back to the `initialize` handshake. Pass `mode='legacy'` to force the initialize handshake and reproduce v1's pre-2026 connection sequence (the per-request wire shape still differs from v1; see [Every outbound request now carries a `_meta` envelope](#every-outbound-request-now-carries-a-_meta-envelope-opentelemetry-is-on-by-default)), or pass a modern protocol-version string (e.g. `mode='2026-07-28'`) to pin a version without probing.

The probe is transport-independent: v2 servers answer it over stdio (and any other stream-pair transport) as well as streamable HTTP, so `mode='auto'` lands on `2026-07-28` against a v2 server on every transport. If your stdio workflow relies on server-initiated requests (sampling, push elicitation), pass `mode='legacy'` — a 2026-07-28 connection refuses them on every transport.

For an in-process `Client(server)` (where `server` is a `Server` or `MCPServer` instance), `mode='auto'` dispatches calls directly through `DirectDispatcher` with no JSON-RPC framing. Pass `mode='legacy'` if you need the in-memory JSON-RPC transport that v1 used.

`Client.send_ping()` is deprecated (ping is removed in 2026-07-28); pin `mode='legacy'` if you need it.

### `ClientSession.get_server_capabilities()` replaced by era-neutral accessors

`ClientSession` now exposes the negotiated server metadata as properties: `server_capabilities`, `server_info`, `instructions`, and `protocol_version`. These are populated by whichever connection step ran (`initialize()` for ≤2025-11-25 servers, `discover()` for 2026-07-28+), and are `None` if none has — matching v1's `get_server_capabilities()`. The `get_server_capabilities()` method has been removed.

**Before (v1):**

```python
capabilities = session.get_server_capabilities()
# server_info, instructions, protocol_version were not stored — had to capture initialize() return value
```

**After (v2):**

```python
capabilities = session.server_capabilities
server_info = session.server_info
instructions = session.instructions
version = session.protocol_version
```

The raw handshake result is also retained: `session.initialize_result` is set after `initialize()` (≤2025-11-25 servers — including `stateless_http=True` servers, which still answer `initialize`); `session.discover_result` is set after `discover()` (2026-07-28+ servers). At most one is non-`None`.

On the high-level `Client`, `client.server_capabilities`, `client.server_info`, and `client.protocol_version` are non-nullable inside the context manager. `client.instructions` remains `str | None` since the server may omit it. (The lowlevel `ClientSession` still lets you call methods before any handshake, as in v1; `Client` always connects on enter — by default it probes `server/discover` and falls back to the initialize handshake.)

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
from mcp_types import PaginatedRequestParams

result = await session.list_resources(params=PaginatedRequestParams(cursor="next_page_token"))
result = await session.list_tools(params=PaginatedRequestParams(cursor="next_page_token"))
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

### Timeouts take `float` seconds instead of `timedelta`

Every timeout parameter that took a `datetime.timedelta` in v1 now takes plain seconds as a `float`:

| Surface | v1 type | v2 type |
|---|---|---|
| `ClientSession(read_timeout_seconds=...)` | `timedelta \| None` | `float \| None` |
| `ClientSession.call_tool(read_timeout_seconds=...)` | `timedelta \| None` | `float \| None` |
| `ClientSession.send_request(request_read_timeout_seconds=...)` | `timedelta \| None` | `float \| None` |
| `ClientSessionGroup.call_tool(read_timeout_seconds=...)` | `timedelta \| None` | `float \| None` |
| `ClientSessionParameters.read_timeout_seconds` | `timedelta \| None` | `float \| None` |
| `StreamableHttpParameters.timeout` / `.sse_read_timeout` | `timedelta` | `float` |
| `ServerSession.send_request(request_read_timeout_seconds=...)` | `timedelta \| None` | `float \| None` |

`SseServerParameters` already used `float` in v1 and is unaffected.

**Before (v1):**

```python
from datetime import timedelta

session = ClientSession(read_stream, write_stream, read_timeout_seconds=timedelta(seconds=30))
result = await session.call_tool("slow_tool", {}, read_timeout_seconds=timedelta(minutes=2))

params = StreamableHttpParameters(
    url="https://example.com/mcp",
    timeout=timedelta(seconds=30),
    sse_read_timeout=timedelta(seconds=300),
)
```

**After (v2):**

```python
session = ClientSession(read_stream, write_stream, read_timeout_seconds=30)
result = await session.call_tool("slow_tool", {}, read_timeout_seconds=120)

params = StreamableHttpParameters(
    url="https://example.com/mcp",
    timeout=30,
    sse_read_timeout=300,
)
```

The failure mode depends on the surface. `StreamableHttpParameters` is a pydantic model, so a leftover timedelta fails loudly at construction (`ValidationError: Input should be a valid number`). The session-path parameters still accept the timedelta at construction or call time; the first request that arms the timeout then crashes inside anyio with `TypeError: unsupported operand type(s) for +: 'float' and 'datetime.timedelta'`, an error that never names the parameter. One narrowing note: v1's `StreamableHttpParameters` coerced bare numbers into timedelta, so v1 code that already passed numbers there keeps working; only explicit-timedelta code breaks.

The same change applies server-side: `ServerSession.send_request(request_read_timeout_seconds=...)`, called from a lowlevel handler via `ctx.session`, is now `float | None`. A v1-style timedelta raises the same anyio `TypeError`, after the request has already been written to the wire, so the handler crashes instead of receiving the response.

To migrate, replace `timedelta(...)` with plain seconds, or mechanically append `.total_seconds()` to an existing timedelta value.

### Client request timeouts now raise `-32001` (`REQUEST_TIMEOUT`) instead of `408`

A client request that exceeds `read_timeout_seconds` still raises the SDK's protocol error (`MCPError`, previously `McpError`), but the error code changed from the HTTP status `408` (`httpx.codes.REQUEST_TIMEOUT`) to the JSON-RPC code `-32001` (`REQUEST_TIMEOUT`, importable from `mcp_types`), matching the TypeScript SDK. The message changed too: v1 said `"Timed out while waiting for response to ClientRequest. Waited 5.0 seconds."`, v2 says `"Request 'tools/call' timed out"`. `MCPError.error` still exists, so a migrated `e.error.code == 408` check runs without error and silently never matches; timeouts fall through to whatever generic-error handling follows. Code that matched on the old message text breaks too. Compare against `REQUEST_TIMEOUT` instead.

**Before (v1):**

```python
import httpx
from mcp.shared.exceptions import McpError

try:
    result = await session.call_tool("slow_tool", {})
except McpError as e:
    if e.error.code == httpx.codes.REQUEST_TIMEOUT:  # 408
        ...  # retry / back off
    else:
        raise
```

**After (v2):**

```python
from mcp.shared.exceptions import MCPError
from mcp_types import REQUEST_TIMEOUT  # -32001

try:
    result = await client.call_tool("slow_tool", {})
except MCPError as e:
    if e.code == REQUEST_TIMEOUT:
        ...  # retry / back off
    else:
        raise
```

`e.error.code` also still works; `e.code` is the v2 convenience property. `mcp.types` no longer exists, so the constant comes from `mcp_types`. The example uses the high-level `Client`; `ClientSession.call_tool()` raises the same `MCPError`.

### `ClientSession` now runs on `JSONRPCDispatcher`; `BaseSession` removed

`ClientSession`'s public surface is unchanged — same constructor apart from timeout parameters (see [Timeouts take `float` seconds instead of `timedelta`](#timeouts-take-float-seconds-instead-of-timedelta)), typed methods, manual `initialize()`, and async context-manager lifecycle — but `BaseSession`, the v1 receive loop underneath it, is removed with no shim. The engine now lives in `JSONRPCDispatcher` (`mcp.shared.jsonrpc_dispatcher`). To customize client behavior, use the `ClientSession` constructor callbacks, or pass a pre-built dispatcher via the new keyword-only `dispatcher=` constructor argument (e.g. a `DirectDispatcher` for in-process embedding).

Behavior changes:

- **Callbacks and notifications now run concurrently.** In v1 the receive loop processed one inbound message at a time, so callbacks ran inline and in order. Now each delivery starts in arrival order but runs as its own task. Server-initiated request callbacks (`sampling`, `elicitation`, `roots`) no longer block other traffic, may themselves send requests without deadlocking, and are interrupted if the server sends `notifications/cancelled` (the request is then answered with an error). Notification callbacks (`logging_callback`, `progress_callback`, `message_handler`) may interleave, and a `progress_callback` may run after the request it reports on has returned; there is no built-in bound on concurrent deliveries. Transport-level errors reach `message_handler` the same way, and a `message_handler` that raises is logged rather than fatal to the session. Callbacks that need strict sequencing must coordinate themselves.
- **Timeouts**: a timed-out or abandoned request is now followed by `notifications/cancelled`, so the server stops the handler instead of leaving it running.
- **A raising request callback** is answered with `code=0` and the exception text; v1 flattened every callback exception to `INVALID_PARAMS`. For a specific error response, return `ErrorData` (unchanged) or raise `MCPError`. One carve-out: pydantic's `ValidationError` is still answered with `INVALID_PARAMS`, as in v1.
- **`send_request` before entering the context manager** raises `RuntimeError` immediately; v1 wrote to the transport and hung until the timeout. After the connection has closed it raises `MCPError` (`CONNECTION_CLOSED`) instead. `send_notification` before entry still works.
- **`send_notification` after the connection has closed is dropped with a debug log instead of raising.** In v1 the send raised `anyio.BrokenResourceError` (peer gone) or `anyio.ClosedResourceError` (session torn down), and this applied to the typed helpers (`send_roots_list_changed`, `send_progress_notification`) too. Code that used the exception as its disconnect signal should probe with a request instead (`send_request` still raises `MCPError` after close, see above) or scope the sending task to the session's lifetime.
- **`send_notification` no longer takes `related_request_id`, and `send_request` no longer accepts `ServerMessageMetadata`.** No client transport ever serialized these hints; progress and response correlation via `progressToken` and the request id is unaffected.
- **Client callbacks now receive `mcp.client.ClientRequestContext`** (its `request_id` is always populated); the `mcp.shared.context.RequestContext` generic is deleted. Annotations spelled `RequestContext[ClientSession, Any]` become `ClientRequestContext` (details in [`RequestContext` type parameters simplified](#requestcontext-type-parameters-simplified)).

`mcp.shared.session` is now a compatibility module: `ProgressFnT` is re-exported (its home is `mcp.shared.dispatcher`), and `RequestResponder` remains as a typing-only stub so `MessageHandlerFnT` annotations keep importing. `RequestResponder.respond()` no longer exists, and neither do the cancellation-tracking members (`cancel()`, the `cancelled` and `in_flight` properties, the `on_complete` constructor argument) or `BaseSession._in_flight`; inbound cancellation is handled by `JSONRPCDispatcher`.

### Experimental Tasks support removed

Tasks ([SEP-1686](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1686)) have been removed from the MCP specification and are no longer part of this SDK. The `mcp.client.experimental`, `mcp.server.experimental`, `mcp.shared.experimental`, and `mcp.server.lowlevel.experimental` modules have been removed, along with the `experimental` properties on `ClientSession`, `ServerSession`, `Server`, and `ServerRequestContext`. The corresponding `Task*` types remain in `mcp_types` as types-only definitions, except the `TaskExecutionMode` alias, whose literal is now inlined on `ToolExecution.task_support`.

The 2026-07-28 revision reintroduces Tasks as an official extension: [SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2663), `io.modelcontextprotocol/tasks`, redesigned around polling (`tasks/get`) instead of a blocking `tasks/result`. This SDK does not implement the extension yet.

## Transports

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

The `GetSessionIdCallback` type alias is gone as well, so `from mcp.client.streamable_http import GetSessionIdCallback` now raises `ImportError`. Drop the annotation, or inline `Callable[[], str | None]` if your own wrapper code still needs the type.

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

### `StreamableHTTPTransport.protocol_version` attribute removed

The transport no longer holds per-connection protocol state; era-dependent headers (e.g. `MCP-Protocol-Version`) are now supplied per-message by the session. If you were reading `transport.protocol_version` to learn the negotiated version, read `session.protocol_version` (or `client.protocol_version` on the high-level `Client`) instead.

The `MCP_PROTOCOL_VERSION` header-name constant has moved: import `MCP_PROTOCOL_VERSION_HEADER` from `mcp.shared.inbound` instead of `MCP_PROTOCOL_VERSION` from `mcp.client.streamable_http`.

### Streamable HTTP: non-2xx responses now surface as per-request JSON-RPC errors

In v1, a non-2xx response to a message POST (other than 404) raised `httpx.HTTPStatusError` inside the transport's task group, so it escaped the `streamable_http_client` context as an `ExceptionGroup` and failed every pending request; a 404 raised `McpError` with the positive literal code `32600`. In v2 the transport no longer raises for HTTP status errors: the failing request gets a JSON-RPC error, raised as `MCPError` from that one call, and the connection stays usable. After a 500 fails one `tools/list`, the next call on the same session succeeds.

| Server response | v1 | v2 |
| --- | --- | --- |
| Non-2xx with a JSON-RPC error body | body discarded; `httpx.HTTPStatusError` escapes the context | body's error surfaced verbatim, e.g. `MCPError(-32602, 'Invalid params')` |
| 404, session established | `McpError` with positive code `32600` | `MCPError(-32600, 'Session terminated')` |
| 404, no session yet | `McpError` with positive code `32600` | `MCPError(-32601, 'Not Found')` |
| Any other 4xx/5xx | `httpx.HTTPStatusError` escapes as `ExceptionGroup` | `MCPError(-32603, 'Server returned an error response')` |

Both common v1 patterns silently stop working: an `except* httpx.HTTPStatusError` around the transport context becomes dead code because status errors no longer escape the context, and a session-expiry check on `error.code == 32600` never matches again because the code is now the standard negative `-32600`.

**Before (v1):**

```python
import httpx
from mcp.shared.exceptions import McpError

while True:
    try:
        async with streamable_http_client(url) as (read, write, _get_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                try:
                    await session.list_tools()
                except McpError as exc:
                    if exc.error.code == 32600:  # v1's "Session terminated"
                        continue  # session expired: rebuild the connection
                    raise
    except* httpx.HTTPStatusError:
        pass  # server returned 4xx/5xx: the loop rebuilds the connection
```

**After (v2):**

```python
from mcp import ClientSession, MCPError
from mcp.client.streamable_http import streamable_http_client
from mcp_types import INVALID_REQUEST  # -32600

async with streamable_http_client(url) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        try:
            await session.list_tools()
        except MCPError as exc:
            if exc.code == INVALID_REQUEST and exc.message == "Session terminated":
                await reconnect()  # session expired: rebuild the connection
            else:
                raise
```

Move HTTP-status failure handling from around the transport context to around the individual calls, catching `MCPError` (see [`McpError` renamed to `MCPError`](#mcperror-renamed-to-mcperror)). Connect-level failures such as `httpx.ConnectError` still escape the transport context as before; keep context-level handling for those only.

### `terminate_windows_process` removed

The deprecated `mcp.os.win32.utilities.terminate_windows_process` function has been
removed. Process termination is handled internally by the `stdio_client` context
manager; there is no replacement API. The Windows tree-termination helper
`terminate_windows_process_tree` no longer accepts a `timeout_seconds` argument —
the value was never used (Job Object termination is immediate).

### `stdio_client` shutdown reworked: a gracefully-exited server's children are left alive on POSIX

When a server exits on its own after `stdio_client` closes its stdin, background
child processes the server leaves behind are deliberately left alive on POSIX:
their lifetime is the server's business. The old shutdown wait was gated on the
stdio pipes closing rather than on process exit, so a child holding an inherited
pipe made a well-behaved server look hung: shutdown stalled for the full grace
period, then attempted a tree-kill that in practice failed against the
already-exited server (its process group could no longer be looked up) and logged
a warning, leaving the children alive anyway. (That gating is an asyncio behavior
specific to Python 3.11+; on Python 3.10 and the trio backend the old wait already
resolved on process exit, so the spurious stall never happened there.) A server that does not exit within the grace
period is still terminated
along with its entire process group. On Windows, children stay in the server's Job
Object and are still killed at shutdown — now deterministically when the job handle
is closed, rather than whenever the handle happened to be garbage-collected.

If you relied on `stdio_client` killing everything the server spawned, make the
server terminate its own children on shutdown (its stdin reaching EOF is the
shutdown signal), or clean up the process tree from the host application after
`stdio_client` exits.

Two related shutdown refinements: `stdio_client` now closes its end of the pipes
deterministically at shutdown, so a surviving child that keeps writing to an
inherited stdout receives `EPIPE`/`SIGPIPE` once the client is gone (previously the
pipe lingered until garbage collection); and a failed write to a server that is
still running now surfaces as a closed connection (`CONNECTION_CLOSED`) on the read
side instead of a raw `BrokenResourceError` escaping the `stdio_client` context.

`terminate_posix_process_tree` now requires the process to lead its own process
group (spawned with `start_new_session=True`); the `getpgid()` lookup and the
per-process terminate/kill fallback are gone. The win32 utilities logger is now
named `mcp.os.win32.utilities` (was `client.stdio.win32`).

### WebSocket transport removed

The WebSocket transport has been removed: `mcp.client.websocket.websocket_client`, `mcp.server.websocket.websocket_server`, and the `ws` optional dependency extra (`mcp[ws]`) no longer exist. WebSocket was never part of the MCP specification. Use the streamable HTTP transport instead (`mcp.client.streamable_http.streamable_http_client` on the client, `streamable_http_app()` on the server), which supports bidirectional communication with server-to-client streaming over standard HTTP.

## OAuth and server auth

### OAuth metadata URLs no longer gain a trailing slash

`OAuthMetadata`, `ProtectedResourceMetadata`, and `OAuthClientMetadata` now set
`url_preserve_empty_path=True` (Pydantic 2.12+). A path-less URL parsed from the wire keeps its
empty path instead of acquiring a trailing slash, so e.g. an `issuer` of `https://as.example.com`
round-trips as `https://as.example.com` rather than `https://as.example.com/`. This matters for
[RFC 9207](https://datatracker.ietf.org/doc/html/rfc9207) / [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) issuer comparisons, which require simple string comparison ([RFC 3986](https://datatracker.ietf.org/doc/html/rfc3986) §6.2.1).
URLs constructed in Python from an already-built `AnyHttpUrl` object are unaffected (they were
normalized at construction); only values parsed from strings/JSON change.

This also changes the wire form of `OAuthClientMetadata.redirect_uris`: a path-less redirect URI
passed as a string (e.g. `redirect_uris=['http://localhost:8080']`) now serializes as
`http://localhost:8080` instead of `http://localhost:8080/`, and the client sends it verbatim in
the `/authorize` and token-exchange requests. [RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749) §3.1.2.3 requires authorization servers to
match redirect URIs by exact string comparison, so if you registered such a URI with a previous SDK
release (with the trailing slash) and the registration is persisted in `TokenStorage`, re-register
the client so the stored value matches what the SDK now transmits.

`AuthSettings` now sets `url_preserve_empty_path=True` for the same reason: a path-less
`issuer_url` (or `resource_server_url`) passed as a string keeps its empty path, so the authorization
server advertises `issuer` as `https://as.example.com` rather than `https://as.example.com/` in its
metadata. Previously the trailing slash was added before the model saw the value, leaving the served
issuer inconsistent with what clients compare against under RFC 8414 / RFC 9207. Passing an
already-built `AnyHttpUrl` object still normalizes at construction; pass a string to get the
preserved form.

### OAuth `callback_handler` returns `AuthorizationCodeResult`

The `callback_handler` passed to `OAuthClientProvider` now returns an `AuthorizationCodeResult` instead of a `tuple[str, str | None]` of `(code, state)`. The new object adds an `iss` field so the client can validate the [RFC 9207](https://datatracker.ietf.org/doc/html/rfc9207) authorization-response issuer ([SEP-2468](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2468)): when the redirect carries an `iss` query parameter it must match the authorization server's issuer, and a missing `iss` is rejected when the server advertised `authorization_response_iss_parameter_supported`.

**Before (v1):**

```python
async def callback_handler() -> tuple[str, str | None]:
    params = parse_qs(urlparse(await wait_for_redirect()).query)
    return params["code"][0], params.get("state", [None])[0]
```

**After (v2):**

```python
from mcp.client.auth import AuthorizationCodeResult


async def callback_handler() -> AuthorizationCodeResult:
    params = parse_qs(urlparse(await wait_for_redirect()).query)
    return AuthorizationCodeResult(
        code=params["code"][0],
        state=params.get("state", [None])[0],
        iss=params.get("iss", [None])[0],
    )
```

Forward the `iss` query parameter from the redirect so the validation can run: omitting it makes the flow fail with `OAuthFlowError` against servers that advertise `authorization_response_iss_parameter_supported`, and silently skips the check for servers that send `iss` without advertising it.

### Client rejects authorization server metadata with a mismatched `issuer`

During OAuth discovery, `OAuthClientProvider` now validates that the authorization server
metadata's `issuer` exactly matches the authorization server URL advertised in the protected
resource metadata, as required by [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414)
section 3.3 ([SEP-2468](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2468)).
The comparison is a simple string comparison ([RFC 3986](https://datatracker.ietf.org/doc/html/rfc3986)
section 6.2.1), so even a trailing-slash disagreement counts as a mismatch. v1 accepted the
metadata without checking, so a server pairing whose two values disagree authenticated fine
under v1 and now fails the entire flow. For example, when the MCP server's protected resource
metadata advertises

```json
{"authorization_servers": ["https://as.example.com"]}
```

while the authorization server's RFC 8414 metadata says `"issuer": "https://as.example.com/"`,
v1 completes discovery and proceeds with the flow; v2 aborts with:

```text
OAuthFlowError: Authorization server metadata issuer mismatch: https://as.example.com/ != https://as.example.com
```

There is no client-side override. Fix the deployment instead: make the authorization server's
`issuer` string-equal the URL in the protected resource metadata's `authorization_servers`
list. See [OAuth metadata URLs no longer gain a trailing slash](#oauth-metadata-urls-no-longer-gain-a-trailing-slash)
for how v2 preserves the exact string form of these URLs.

### OAuth client requests `offline_access` and adds `prompt=consent` when the authorization server supports it ([SEP-2207](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2207))

The OAuth client now augments its requested scope with `offline_access` whenever the
authorization server's metadata advertises that scope in `scopes_supported` and the client's
`grant_types` include `refresh_token`, which is the default. When `offline_access` ends up in
the requested scope, the authorization request also carries `prompt=consent`, as OIDC requires
for offline access. Against an authorization server that advertises `offline_access` (Keycloak
and Auth0 do by default), an unchanged v1 client sends a different authorization URL:

**Before (v1):**

```text
https://as.example.com/authorize?...&scope=read
```

**After (v2):**

```text
https://as.example.com/authorize?...&scope=read offline_access&prompt=consent
```

Three observable consequences: end users see an interactive consent screen on every
authorization where OIDC providers previously re-authorized returning users silently, the
granted scope is broader with refresh tokens issued and persisted through `TokenStorage` where
v1 never requested them, and strict authorization servers that reject un-allowlisted scopes may
fail the flow with `invalid_scope`. The `prompt=consent` half applies even when
`offline_access` was already part of the scope selection in v1.

To keep the v1 behavior (no `offline_access` request, no consent prompt, no refresh tokens),
restrict the client's grant types:

```python
client_metadata = OAuthClientMetadata(
    client_name="my-client",
    redirect_uris=["http://localhost:3000/callback"],
    grant_types=["authorization_code"],
)
```

Note this also registers the client without the `refresh_token` grant, so token refresh is
disabled; there is no knob for refresh tokens without the forced consent screen, since
`prompt=consent` is keyed off the final scope.

### OAuth client credentials are bound to their authorization server ([SEP-2352](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2352))

Persisted OAuth client credentials are now bound to the authorization server that issued them: `OAuthClientInformationFull` records an `issuer`, set by the SDK after registration. When a server's protected resource metadata later points at a different authorization server, the client discards the bound credentials (and the old tokens) and re-registers with the new server instead of presenting one server's `client_id` to another. URL-based client IDs (CIMD) are portable and unaffected; credentials with no recorded issuer (pre-registered, or stored before this change) are left as-is. No API change for existing `TokenStorage` implementations - the `issuer` round-trips through the unchanged `get_client_info`/`set_client_info`.

### Step-up authorization unions previously requested scopes ([SEP-2350](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2350))

When a `403 insufficient_scope` challenge triggers step-up re-authorization, the OAuth client now requests the union of the previously requested scopes and the newly challenged scopes, instead of replacing the scope with only the challenged ones. This keeps permissions granted for earlier operations from being dropped when a later operation escalates. No API change; the wider scope is sent automatically on the re-authorization request.

### OAuth Dynamic Client Registration sends `application_type` ([SEP-837](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/837))

`OAuthClientMetadata` now carries an `application_type` field that is sent during Dynamic Client Registration. It defaults to `"native"`, which suits MCP clients that use loopback redirect URIs (CLI and desktop apps); browser-based clients served from a non-local host should set it to `"web"`:

```python
from mcp.shared.auth import OAuthClientMetadata

client_metadata = OAuthClientMetadata(
    redirect_uris=["https://app.example.com/callback"],
    application_type="web",
)
```

Under OIDC, omitting `application_type` defaults to `"web"`, which an authorization server may reject for the `localhost` redirect URIs native clients use; sending `"native"` avoids that. Non-OIDC servers ignore the parameter.

### Stricter client authentication at `/token` and `/revoke`

v2 hardens client authentication on SDK-hosted authorization servers (`create_auth_routes`) in two ways. Both apply automatically; server code only needs changing if you hand-provision client records.

**Client-auth failures now return `invalid_client`.** In v1, every `ClientAuthenticator` failure at `/token` (unknown `client_id`, wrong secret, expired secret) returned HTTP 401 with `unauthorized_client`. v2 returns `invalid_client`, the code [RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749) §5.2 assigns to failed client authentication:

```text
# v1
401 {"error":"unauthorized_client","error_description":"Invalid client_id"}
# v2
401 {"error":"invalid_client","error_description":"Invalid client_id"}
```

`unauthorized_client` is now reserved for a client that authenticated successfully but is not permitted the requested grant. Update any client code, integration tests, or alerting that string-matches the old error code, or accept both while clients and servers migrate at different times.

**Secret-based clients without a stored secret are rejected.** In v1, `ClientAuthenticator` only validated a secret when one was stored, so a hand-provisioned client record with a secret-based auth method but no secret authenticated with no credentials at all. v2 rejects such clients before any grant processing: `/token` returns 401 `invalid_client` and `/revoke` returns 401 `unauthorized_client`, both with the description "Client is registered for secret-based authentication but has no stored secret". Only records that explicitly set `client_secret_post` or `client_secret_basic` with no secret are affected: records left at the default `token_endpoint_auth_method=None` fail in both versions, and DCR-registered clients always receive a generated secret.

**Before (v1):**

```python
from mcp.shared.auth import OAuthClientInformationFull

LEGACY_CLIENT = OAuthClientInformationFull(
    client_id="legacy-client",
    client_secret=None,  # no secret stored
    token_endpoint_auth_method="client_secret_post",  # but a secret-based method
    redirect_uris=["http://localhost:1234/cb"],
)
```

**After (v2):** either register the client as public, or store a secret that clients must then present:

```python
LEGACY_CLIENT = OAuthClientInformationFull(
    client_id="legacy-client",
    token_endpoint_auth_method="none",  # public client, no secret expected
    redirect_uris=["http://localhost:1234/cb"],
)
```

## Stricter protocol validation and wire behavior

### Server handler results are validated against the protocol schema

Results returned from server handlers are now validated against the negotiated protocol version's schema before being sent. A result that does not conform raises on the server side and the client receives an `INTERNAL_ERROR` response. The case most existing code will hit is `Tool.inputSchema`: the spec requires it to contain `"type": "object"`, so an empty `{}` is now rejected.

### Client validates inbound traffic against the protocol schema

`ClientSession` now validates server requests, notifications, and results against the negotiated protocol version's schema before parsing them into `mcp_types` models. Spec-invalid server output that the previous monolith parse tolerated may now raise `pydantic.ValidationError` from `list_tools()`, `call_tool()`, and similar calls. `_meta` remains the sanctioned place for result extras (and `experimental` for capability extras).

### Unknown request methods now return `-32601` (Method not found)

In v1, a request for a method the SDK didn't recognize failed request-union validation and was answered with `-32602` (`"Invalid request parameters"`, empty `data`). Any method the receiver doesn't serve — unrecognized on either side, or a spec method the server has no registered handler for — is now answered with the JSON-RPC-specified `-32601` (`"Method not found"`), with the method name in `data`, in every initialization state. Clients still decline sampling, elicitation, and roots requests with `-32600` when no callback is registered, as in v1. Update anything that matched on the old code for this case.

### Every outbound request now carries a `_meta` envelope; OpenTelemetry is on by default

v2 sends `"_meta": {}` in the params of every request it emits, at every negotiated protocol version. Requests that had no params in v1, such as `ping` and `tools/list`, now carry `"params": {"_meta": {}}`; server-initiated requests get the same envelope. This is spec-valid and accepted by all peers, but wire traffic differs from v1 on every call, and no configuration restores the v1 wire shape. Update any test or tooling that asserts on raw outbound request bytes.

**Before (v1):** same client code, 2025-11-25 peer:

```text
{"method":"ping","jsonrpc":"2.0","id":1}
{"method":"tools/list","jsonrpc":"2.0","id":2}
```

**After (v2):**

```text
{"jsonrpc":"2.0","id":2,"method":"ping","params":{"_meta":{}}}
{"jsonrpc":"2.0","id":3,"method":"tools/list","params":{"_meta":{}}}
```

The envelope exists for OpenTelemetry trace propagation ([SEP-414](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/414)), which now ships enabled: every server installs a tracing middleware and the client opens a span per outbound request. With no OpenTelemetry SDK configured these are no-ops and only the empty envelope is visible. If your application already configures a global tracer provider, it starts recording MCP client and server spans with no code change, and a W3C `traceparent` field is injected into outbound `_meta`, propagating your trace ids to the servers you call. To suppress the spans, filter the `mcp-python-sdk` tracer in your pipeline; [OpenTelemetry](run/opentelemetry.md) has the recipe for removing the server middleware. There is no public switch for the client-side span and `traceparent` injection.

The SDK's new `opentelemetry-api` runtime dependency is covered under [Packaging, dependencies, and CLI](#packaging-dependencies-and-cli).

## Testing utilities

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

`Client` accepts the same callback parameters the old helper did (`sampling_callback`, `list_roots_callback`, `logging_callback`, `message_handler`, `elicitation_callback`, `client_info`), keeps `raise_exceptions` for surfacing server-side errors and `read_timeout_seconds` (now a plain `float` of seconds rather than a `timedelta`; see [Timeouts take `float` seconds instead of `timedelta`](#timeouts-take-float-seconds-instead-of-timedelta)), and adds `mode` to control version negotiation (`'auto'` by default; `'legacy'` reproduces v1's initialize-only handshake).

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

Note that the streams it yields are now context-propagating wrappers (`ContextReceiveStream`/`ContextSendStream`) rather than plain anyio memory streams. They support `send`, `receive`, async iteration, `close`, `aclose`, and `clone`, but the anyio-only methods `send_nowait`, `receive_nowait`, and `statistics()` are gone and raise `AttributeError`; use `await send(...)`/`await receive()` instead, or create plain `anyio.create_memory_object_stream` pairs yourself if you need the full anyio API.

One behavioral caveat when moving progress-reporting handlers onto `Client(server)`: reading `ctx.meta["progress_token"]` and calling `session.send_progress_notification(token, ...)` is specific to the JSON-RPC transport path. On the in-process modern path (`DirectDispatcher` / `Client(server)`), there is no wire token in `_meta`, so handlers that gate progress on the token's presence go silent.

`ctx.report_progress(progress, total, message)` works on every dispatcher: it sends a progress notification when a token is present and routes the update through the dispatcher's progress channel otherwise, no-opping only when the caller did not request progress at all (see also [Client-to-server progress deprecated](#client-to-server-progress-deprecated-2026-07-28)). `session.send_progress_notification(progress_token, ...)` is unchanged and still works on JSON-RPC transports for code that already holds a token.

## Deprecations

### Roots, Sampling, and Logging methods deprecated (SEP-2577)

[SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) deprecates the Roots, Sampling, and Logging features as of the 2026-07-28 spec. The deprecation is advisory only: there are no wire-level changes, capability negotiation is unchanged, and every method keeps working for sessions negotiating 2025-11-25 and earlier.

The user-facing methods for these features now carry `typing_extensions.deprecated`, so type checkers, IDEs, and the runtime surface a deprecation warning where they are called:

- Sampling: `ServerSession.create_message()`, `ClientPeer.sample()`
- Roots: `ServerSession.list_roots()`, `ClientPeer.list_roots()`, `ClientSession.send_roots_list_changed()`, `Client.send_roots_list_changed()`
- Logging: `ServerSession.send_log_message()`, `Connection.log()`, `ClientSession.set_logging_level()`, `Client.set_logging_level()`, `mcp.server.context.Context.log()` (the lowlevel `Context`), and the `MCPServer` `Context` helpers `log()`, `debug()`, `info()`, `warning()`, `error()`

Registering a handler for a deprecated capability is deprecated too. The `Server.__init__` parameters `on_set_logging_level` (Logging) and `on_roots_list_changed` (Roots) are now split out into a `typing_extensions.deprecated` overload, so passing either is flagged by type checkers and emits `mcp.MCPDeprecationWarning` at construction time. `on_progress` follows the same pattern (see below). The non-deprecated overload omits these parameters, so the common case stays warning-free.

The runtime warning is emitted as `mcp.MCPDeprecationWarning`, which subclasses `UserWarning` (not `DeprecationWarning`) so it is visible by default. To silence it, filter that category:

```python
import warnings
from mcp import MCPDeprecationWarning

warnings.filterwarnings("ignore", category=MCPDeprecationWarning)
```

No migration is required during the deprecation window. New code should avoid building on these features, since they may be removed in a future spec version.

### Client-to-server progress deprecated (2026-07-28)

The 2026-07-28 spec restricts `notifications/progress` to the server-to-client direction only — `ProgressNotification` is no longer in the spec's `ClientNotification`. `Client.send_progress_notification()` and `ClientSession.send_progress_notification()` now carry `typing_extensions.deprecated` and emit `mcp.MCPDeprecationWarning` at runtime. They continue to work against servers negotiating 2025-11-25 or earlier. Registering a lowlevel `Server` `on_progress` handler is deprecated the same way as the SEP-2577 handler parameters above: it sits in the `typing_extensions.deprecated` `Server.__init__` overload and passing it emits `mcp.MCPDeprecationWarning` at construction time.

On the server side, prefer the new dispatcher-agnostic `ServerSession.report_progress(progress, total, message)` (and `Context.report_progress()` on `MCPServer`) over the raw `ServerSession.send_progress_notification(progress_token, …)`. `report_progress` encapsulates the "no-op when the caller did not request progress" rule and works on every dispatcher; the raw token-taking form remains for handlers that read `_meta.progressToken` directly.

## Notes for 2026-era connections

Everything below this heading describes behavior that only activates on connections
negotiated at protocol 2026-07-28 or later. Migrated v1 code talking to 2025-11-25 (or
earlier) peers is unaffected. It is collected here so the rest of this guide stays
focused on the v1-to-v2 upgrade itself.

### Servers validate `Mcp-Param-*` headers against the request body ([SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243))

On the 2026-07-28 Streamable HTTP path, a `tools/call` whose tool declares `x-mcp-header` annotations is validated before dispatch — each annotated argument and its mirroring `Mcp-Param-*` header must be present together and agree (after base64-sentinel decoding; integers compare numerically), or absent together. A violation is rejected with HTTP 400 and JSON-RPC error `-32020` (`HeaderMismatch`), as the spec requires. A client that sends an annotated argument *without* its header — for example one that never listed the tool — is therefore rejected instead of silently served; the spec's recovery is to re-list and retry. On the client side, `ClientSession.call_tool` emits these headers automatically for annotated arguments of any tool it has listed; list the tool first, and note that pre-2026 connections and non-HTTP transports never emit them.

There is nothing to configure. The server resolves the called tool's schema through its own registered `tools/list` handler (for `MCPServer`, the built-in one), so the validated catalog is exactly what that caller would be shown. Two consequences worth knowing: the listing runs internally on validated calls, so middleware and an expensive or paginated `tools/list` handler see extra invocations; and validation is skipped — never failing the call — when no `tools/list` handler is registered, the tool isn't in the listing, the handler raises (logged as an error), or the call has no arguments and no `Mcp-Param-*` headers. Headers with no matching annotation are ignored; a recognized header supplied more than once is rejected, as is a duplicated `MCP-Protocol-Version`, `Mcp-Method`, or `Mcp-Name` line. The codec and validator are public in `mcp.shared.inbound` (`decode_header_value`, `validate_mcp_param_headers`) for low-level servers hosting their own HTTP entry.

Base64-sentinel decoding is strict everywhere it applies, including the `Mcp-Name` header: a `=?base64?...?=` value whose payload is not canonical base64 (wrong padding, stray characters, non-zero trailing bits) or not valid UTF-8 is rejected as malformed rather than leniently decoded.

## Need Help?

If you encounter issues during migration:

1. Check the [API Reference](api/mcp/index.md) for updated method signatures
2. Review the [examples](https://github.com/modelcontextprotocol/python-sdk/tree/main/examples) for updated usage patterns
3. Open an issue on [GitHub](https://github.com/modelcontextprotocol/python-sdk/issues) if you find a bug or need further assistance
