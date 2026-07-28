# Migration Guide: v1 to v2

This guide covers the breaking changes in v2 of the MCP Python SDK and how to update code written against v1.x.

## Find your changes

Every section heading names the API it affects, so searching this page for the symbol your code uses is the fastest route to the change that broke it. The guide lists changes only: an SDK API not mentioned here behaves as it did in v1.

### Changes almost every project hits

| Change | First symptom | Section |
|---|---|---|
| `FastMCP` renamed to `MCPServer` | `ModuleNotFoundError: No module named 'mcp.server.fastmcp'` | [`FastMCP` renamed](#fastmcp-renamed-to-mcpserver) |
| Fields renamed from camelCase to snake_case | `AttributeError: 'Tool' object has no attribute 'inputSchema'` | [snake_case fields](#field-names-changed-from-camelcase-to-snake_case) |
| `mcp.types` names removed | `ImportError: cannot import name 'Content' from 'mcp.types'` | [Removed types](#removed-type-aliases-and-classes) |
| `McpError` renamed to `MCPError` | `ImportError: cannot import name 'McpError' from 'mcp'` | [`McpError` renamed](#mcperror-renamed-to-mcperror) |
| Resource URIs are `str`, not `AnyUrl` | `AttributeError: 'str' object has no attribute 'host'` | [URI type](#resource-uri-type-changed-from-anyurl-to-str) |
| Message unions (`ServerNotification`, `JSONRPCMessage`, ...) are plain unions, not `RootModel` | `AttributeError: 'LoggingMessageNotification' object has no attribute 'root'` | [`RootModel` → unions](#replace-rootmodel-by-union-types-with-typeadapter-validation) |
| `streamablehttp_client` removed | `ImportError: cannot import name 'streamablehttp_client'` | [`streamablehttp_client`](#streamablehttp_client-removed) |
| `httpx` and `httpx-sse` replaced by `httpx2` | `ModuleNotFoundError: No module named 'httpx'`, or `TypeError: Invalid "auth" argument` from `httpx.AsyncClient(auth=provider)` | [`httpx2` swap](#httpx-and-httpx-sse-replaced-by-httpx2) |
| Transport parameters moved off the `MCPServer` constructor | `TypeError: MCPServer.__init__() got an unexpected keyword argument 'port'` | [constructor parameters](#transport-parameters-moved-off-the-mcpserver-constructor) |
| Sync handlers run on a worker thread | `asyncio.get_running_loop()` in a `def` handler raises `RuntimeError` | [worker threads](#sync-handler-functions-now-run-on-a-worker-thread) |
| Lowlevel decorators replaced with `on_*` constructor params | `AttributeError: 'Server' object has no attribute 'list_tools'` | [`on_*` handlers](#lowlevel-server-decorator-based-handlers-replaced-with-constructor-on_-params) |
| Lowlevel return value wrapping removed | bare list or dict returns fail result validation instead of being wrapped | [wrapping removed](#lowlevel-server-automatic-return-value-wrapping-removed) |
| Lowlevel tool exceptions no longer become `isError: true` results | clients raise a JSON-RPC error instead of seeing the error text | [tool exceptions](#lowlevel-server-tool-handler-exceptions-no-longer-become-calltoolresultis_errortrue) |
| In-process test client negotiates 2026-07-28 | sampling/elicitation tests raise `NoBackChannelError`; logging callbacks go quiet | [default connection](#behavior-changes-on-v2s-default-connection) |
| Deprecated v1 calls emit `MCPDeprecationWarning` | warnings-as-errors test runs fail on unchanged code | [deprecation warnings](#deprecated-v1-calls-now-warn-breaks-warnings-as-errors-test-runs) |

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
| use sampling, elicitation, roots, logging, or change notifications from handlers | [Behavior changes on v2's default connection](#behavior-changes-on-v2s-default-connection) |

## Suggested migration order

1. Update your dependency pins: [Packaging, dependencies, and CLI](#packaging-dependencies-and-cli).
2. Apply the mechanical renames and import moves: [Types and wire format](#types-and-wire-format).
3. Port your server surface: [MCPServer (formerly FastMCP)](#mcpserver-formerly-fastmcp) or [Lowlevel Server](#lowlevel-server).
4. Port your client code: [Clients](#clients).
5. Update transport setup and auth: [Transports](#transports) and [OAuth and server auth](#oauth-and-server-auth).
6. Run your tests and check anything that now errors against [Stricter protocol validation and wire behavior](#stricter-protocol-validation-and-wire-behavior), [Testing utilities](#testing-utilities), and [Behavior changes on v2's default connection](#behavior-changes-on-v2s-default-connection).

## Packaging, dependencies, and CLI

### Dependency requirements changed

A pin or cap in your project that conflicts with a new floor makes dependency resolution fail (uv reports "No solution found when resolving dependencies"), and code that imported a dropped package without declaring it must now depend on it directly:

| Dependency | v1.x | v2 | Change |
|---|---|---|---|
| anyio | `>=4.5` | `>=4.9` (`>=4.10` on Python 3.14+) | floor raised |
| pydantic | `>=2.11,<3` (`>=2.12,<3` on Python 3.14+) | `>=2.12` | floor raised on Python <3.14; `<3` cap dropped |
| sse-starlette | `>=1.6.1` | `>=3.0.0` | floor raised to 3.x |
| typing-extensions | `>=4.9.0` | `>=4.13.0` | floor raised |
| pywin32 (Windows) | `>=310` (`>=311` on Python 3.14+) | `>=311` | floor raised on Python <3.14 |
| httpx | `>=0.27.1,<1.0.0` | removed | see [`httpx` and `httpx-sse` replaced by `httpx2`](#httpx-and-httpx-sse-replaced-by-httpx2) |
| httpx-sse | `>=0.4` | removed | see above |
| pydantic-settings | `>=2.5.2` | removed | no longer installed with `mcp`; declare it yourself if you import `pydantic_settings` |
| websockets (`ws` extra) | `>=15.0.1` | removed | see [WebSocket transport removed](#websocket-transport-removed) |
| httpx2 | not a dependency | `>=2.5.0` | new required dependency |
| mcp-types | not a dependency | pinned to the exact `mcp` version | new required dependency; do not pin it separately from `mcp` |
| opentelemetry-api | not a dependency | `>=1.28.0` | new required dependency; tracing is a no-op until you install an OpenTelemetry SDK ([OpenTelemetry](run/opentelemetry.md)) |

Relax any conflicting pin. sse-starlette moves to 3.x, so code that imports `sse_starlette` directly must also port to its 3.x API.

### `httpx` and `httpx-sse` replaced by `httpx2`

The SDK depends on [`httpx2`](https://pypi.org/project/httpx2/) (a fork of `httpx` with server-sent events built in) instead of `httpx` and `httpx-sse`, and installs neither. Parameter lists are unchanged; every `httpx` type in the client API is now its `httpx2` equivalent: `http_client=` on `streamable_http_client` is an `httpx2.AsyncClient` (as is whatever your `sse_client(httpx_client_factory=...)` returns), and `auth=` on `sse_client` is an `httpx2.Auth`, so a custom `httpx.Auth` subclass re-bases onto `httpx2.Auth`. If you built the client only to get default behavior, `Client("http://.../mcp")` needs no HTTP client at all; see [Client transports](client/transports.md).

**Before (v1):**

```python
import httpx

http_client = httpx.AsyncClient(headers={"Authorization": "Bearer <token>"})
try:
    ...
except httpx.ConnectError:
    ...
```

**After (v2):**

```python
import httpx2

http_client = httpx2.AsyncClient(headers={"Authorization": "Bearer <token>"})
try:
    ...
except httpx2.ConnectError:
    ...
```

`httpx2` keeps the `httpx` API, so usually only the import name changes; direct `httpx-sse` usage becomes `httpx2.EventSource` or `AsyncClient.sse()`. Code that imported `httpx` or `httpx_sse` only because v1 pulled them in now fails with `ModuleNotFoundError: No module named 'httpx'`: declare `httpx` in your own dependencies (the two packages install side by side) or port those calls.

The transports raise `httpx2` exceptions (`httpx2.ConnectError`, `httpx2.HTTPStatusError`, and so on), so an old `except httpx.ConnectError:` clause silently never matches if `httpx` is still installed; audit `except` clauses, `isinstance` checks, and test fixtures (`pytest.raises(httpx.ConnectError)`, `httpx.MockTransport`, test-only `httpx.Auth` subclasses) along with the imports.

The objects are not interchangeable either: an `httpx.AsyncClient` passed as `http_client=` still connects, but its server-to-client GET stream never opens, so server-initiated messages silently stop arriving.

The SDK's own auth providers made the same move: `OAuthClientProvider`, `ClientCredentialsOAuthProvider`, and `PrivateKeyJWTOAuthProvider` subclass `httpx2.Auth` (v1: `httpx.Auth`), so the client you attach one to must be an `httpx2.AsyncClient`; `httpx.AsyncClient(auth=provider)` fails at construction with `TypeError: Invalid "auth" argument`. See [OAuth clients](client/oauth-clients.md).

Log filters and instrumentation keyed to the `httpx`/`httpcore` names no longer see the SDK's traffic: the loggers are `httpx2` and `httpcore2.*` (target `logging.getLogger("httpx2")` and `logging.getLogger("httpcore2")`), the default User-Agent is `python-httpx2/<version>`, and OpenTelemetry's httpx instrumentation does not hook `httpx2`.

TLS verification changes too: `httpx` validated certificates against the bundled `certifi` CA list, while `httpx2` validates against the operating-system trust store via [`truststore`](https://pypi.org/project/truststore/). With no usable system CA store (some minimal containers), point `SSL_CERT_FILE` or `SSL_CERT_DIR` at a CA bundle (checked before the system store) or pass an explicit `verify=ssl_context` to your `httpx2.AsyncClient`.

## Types and wire format

### `mcp.types` moved to the `mcp-types` package

The protocol wire types now ship in a separate distribution, `mcp-types` (import package `mcp_types`, [API reference](api/mcp_types/index.md)); `mcp` depends on the identically-versioned `mcp-types`, so it installs with `mcp`. `mcp.types` is a permanent alias of `mcp_types` (every name is the same object), so `import mcp.types as types`, `from mcp.types import ...`, `from mcp import types`, and the top-level re-exports (`from mcp import Tool`) all still work. Keep importing through `mcp`; import `mcp_types` directly only in a project that depends on `mcp-types` without the SDK.

The one module that did move is `mcp.shared.version`: its constants live in `mcp.types.version` and changed meaning as well, see [`LATEST_PROTOCOL_VERSION` and `SUPPORTED_PROTOCOL_VERSIONS` changed](#latest_protocol_version-and-supported_protocol_versions-changed).

### Removed type aliases and classes

These `mcp.types` names are gone:

| Removed | Replacement |
|---------|-------------|
| `Content` | `ContentBlock` |
| `ResourceReference` | `ResourceTemplateReference` |
| `Cursor` | `str` |
| `AnyFunction` | `Callable[..., Any]` |
| `MethodT`, `RequestParamsT`, `NotificationParamsT` | internal `TypeVar`s; no longer exported |
| `ClientRequestType`, `ClientNotificationType`, `ClientResultType`, `ServerRequestType`, `ServerNotificationType`, `ServerResultType` | the union now has the bare name (`ClientRequest`, `ClientNotification`, `ClientResult`, `ServerRequest`, `ServerNotification`, `ServerResult`); see [Replace `RootModel` by union types with `TypeAdapter` validation](#replace-rootmodel-by-union-types-with-typeadapter-validation) |
| `TaskExecutionMode`, `TASK_FORBIDDEN`, `TASK_OPTIONAL`, `TASK_REQUIRED`, `TASK_STATUS_*` | string literals; `TaskStatus` remains as the literal-union type; see [Experimental Tasks support removed](#experimental-tasks-support-removed) |

**Before (v1):**

```python
from mcp.types import Content, Cursor, ResourceReference

def render(block: Content, cursor: Cursor | None = None) -> str: ...

ref = ResourceReference(type="ref/resource", uri="file:///{name}")
```

**After (v2):**

```python
from mcp.types import ContentBlock, ResourceTemplateReference

def render(block: ContentBlock, cursor: str | None = None) -> str: ...

ref = ResourceTemplateReference(type="ref/resource", uri="file:///{name}")
```

### Field names changed from camelCase to snake_case

Every field on the protocol type models (`mcp.types`) is now snake_case in Python. The JSON wire format is unchanged: the SDK still sends camelCase through Pydantic aliases.

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
|-----------------|-----------------|
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

Rename attribute access and constructor kwargs alike: `tool.input_schema`, `Tool(input_schema={...})`. A leftover camelCase kwarg such as `Tool(inputSchema={...})` still runs but fails type checking. Parsing is unaffected: `model_validate()` accepts camelCase wire JSON and snake_case dumps alike.

**If you serialize models yourself, pass `by_alias=True`.** `model_dump()` and `model_dump_json()` now silently emit snake_case keys instead of the camelCase wire format:

```python
tool.model_dump()                                # {"name": ..., "input_schema": ...}
tool.model_dump(by_alias=True, mode="json")      # {"name": ..., "inputSchema": ...}  (wire format)
```

### Extra fields on MCP types are no longer preserved

v1 protocol models set `extra="allow"`, so unknown fields passed to a constructor or received from a peer were stored and re-serialized. v2 models silently drop them during validation: the data no longer round-trips, and reading it back as an attribute (`result.customField`) raises `AttributeError`. Carry custom data in `_meta` instead.

**Before (v1):**

```python
from mcp.types import CallToolResult

result = CallToolResult.model_validate({"content": [], "customField": "x"})
result.model_dump()["customField"]  # 'x'
```

**After (v2):**

```python
from mcp.types import CallToolResult

result = CallToolResult.model_validate({"content": [], "customField": "x"})
"customField" in result.model_dump()  # False

result = CallToolResult(content=[], _meta={"myapp/custom": "x"})
result.meta  # {'myapp/custom': 'x'}
```

### Resource URI type changed from `AnyUrl` to `str`

The `uri` field on resource types and the `uri` parameter of the client's `read_resource()`, `subscribe_resource()`, and `unsubscribe_resource()` are now plain `str`. Passing an `AnyUrl` object raises `ValidationError` ("Input should be a valid string"); wrap it in `str(...)`. URIs you read back are strings too, so attribute access like `uri.scheme` or `uri.host` raises `AttributeError`; parse with `urllib.parse`.

**Before (v1):**

```python
from pydantic import AnyUrl
from mcp.types import Resource

resource = Resource(name="test", uri=AnyUrl("resource://items/1"))
scheme = resource.uri.scheme
result = await session.read_resource(AnyUrl("resource://items/1"))
```

**After (v2):**

```python
from urllib.parse import urlparse

from mcp.types import Resource

resource = Resource(name="test", uri="resource://items/1")
scheme = urlparse(resource.uri).scheme
result = await session.read_resource("resource://items/1")
```

Affected `uri` fields: `Resource` (and `ResourceLink`), `ResourceContents` (`TextResourceContents`, `BlobResourceContents`), `ReadResourceRequestParams`, `SubscribeRequestParams`, `UnsubscribeRequestParams`, `ResourceUpdatedNotificationParams`, and the `MCPServer` resource classes (`TextResource`, `FileResource`, ...).

The string is no longer validated or normalized: relative URIs such as `users/me`, which v1 rejected, are accepted, and `https://example.com` is sent as given rather than as `https://example.com/`.

### Replace `RootModel` by union types with `TypeAdapter` validation

`ClientRequest`, `ServerRequest`, `ClientNotification`, `ServerNotification`, `ClientResult`, `ServerResult`, and `JSONRPCMessage` are now plain `X | Y` unions of the concrete pydantic classes, not `RootModel` subclasses, so `.root`, `model_validate()`, and the wrapper call are gone. Validate raw data with the matching `TypeAdapter`:

**Before (v1):**

```python
from mcp.types import ClientRequest, ServerNotification

request = ClientRequest.model_validate(data)
actual_request = request.root

notification = ServerNotification.model_validate(data)
actual_notification = notification.root
```

**After (v2):**

```python
from mcp.types import client_request_adapter, server_notification_adapter

request = client_request_adapter.validate_python(data)  # already the concrete type
notification = server_notification_adapter.validate_python(data)
```

| Union | Adapter (exported from `mcp.types`) |
|-------|--------------------------------------|
| `ClientRequest` | `client_request_adapter` |
| `ServerRequest` | `server_request_adapter` |
| `ClientNotification` | `client_notification_adapter` |
| `ServerNotification` | `server_notification_adapter` |
| `ClientResult` | `client_result_adapter` |
| `ServerResult` | `server_result_adapter` |
| `JSONRPCMessage` | `jsonrpc_message_adapter` |

Constructing a value drops the wrapper only; pass the member (and its `params`) directly:

**Before (v1):**

```python
from mcp.types import ClientNotification, ClientRequest, InitializedNotification, ListToolsRequest, ListToolsResult

await session.send_notification(ClientNotification(InitializedNotification()))
result = await session.send_request(ClientRequest(ListToolsRequest()), ListToolsResult)
```

**After (v2):**

```python
from mcp.types import (
    CancelledNotification,
    CancelledNotificationParams,
    InitializedNotification,
    ListToolsRequest,
    ListToolsResult,
)

await session.send_notification(InitializedNotification())
result = await session.send_request(ListToolsRequest(), ListToolsResult)
await session.send_notification(
    CancelledNotification(params=CancelledNotificationParams(request_id=request_id, reason="timeout"))
)
```

Values the SDK hands you are the member instances themselves. `isinstance(msg, ServerNotification)`, `isinstance(msg, LoggingMessageNotification)`, and `match`/`case` on the member classes keep working; `.root` accesses do not (`AttributeError: 'LoggingMessageNotification' object has no attribute 'root'`), so a `message_handler` becomes:

```python
# Before (v1)
if isinstance(message, ServerNotification):
    if isinstance(message.root, LoggingMessageNotification):
        print(message.root.params.data)

# After (v2)
if isinstance(message, LoggingMessageNotification):
    print(message.params.data)
```

Custom transports and `EventStore` implementations follow the same rule: `mcp.shared.message.SessionMessage` takes the member directly (`SessionMessage(JSONRPCNotification(...))`, not `SessionMessage(JSONRPCMessage(JSONRPCNotification(...)))`), and raw JSON parses with `jsonrpc_message_adapter.validate_json(raw)` instead of `JSONRPCMessage.model_validate_json(raw)`. A parsed `JSONRPCError` may now carry `id=None` (JSON-RPC 2.0 allows it; v1 rejected such messages), so `JSONRPCError.id` is typed `RequestId | None` and code that read it as a definite `str | int` needs a `None` check.

### `RequestParams.Meta` replaced with the `RequestParamsMeta` TypedDict

The nested `RequestParams.Meta` Pydantic model is now the `RequestParamsMeta` TypedDict (`from mcp.types import RequestParamsMeta`), and the nested `NotificationParams.Meta` class is gone: notification `_meta` is a plain `dict[str, Any]`. `ctx.meta` (lowlevel handlers, client callbacks) and `ctx.request_context.meta` (`MCPServer` handlers) are dicts, so attribute access becomes key access, `progressToken` becomes the optional `progress_token` key, and `_meta` you built with `types.RequestParams.Meta(...)` or `types.NotificationParams.Meta(...)` is passed as a plain dict. The wire format is unchanged.

If you only read `progressToken` to send progress, call `report_progress()` instead: it is a no-op when the caller did not request progress and also delivers on the default in-process `Client(server)`, where `ctx.meta` carries no `progress_token` even when the caller passed `progress_callback` (see [Progress](handlers/progress.md)).

**Before (v1):**

```python
ctx = server.request_context
if ctx.meta and ctx.meta.progressToken:
    await ctx.session.send_progress_notification(ctx.meta.progressToken, 0.5, 100)
```

**After (v2):**

```python
await ctx.session.report_progress(0.5, 100)  # lowlevel handler, ctx: ServerRequestContext
# in an MCPServer handler with ctx: Context:
await ctx.report_progress(0.5, 100)
```

For other `_meta` keys use dictionary access; `meta` is still `None` when the request carries no `_meta`:

**Before (v1):**

```python
trace = ctx.meta.traceparent  # extra keys were attributes
```

**After (v2):**

```python
trace = (ctx.meta or {}).get("traceparent")
```

### `LATEST_PROTOCOL_VERSION` and `SUPPORTED_PROTOCOL_VERSIONS` changed

Both constants moved from `mcp.shared.version` to `mcp.types.version` (see [`mcp.types` moved to the `mcp-types` package](#mcptypes-moved-to-the-mcp-types-package)) and changed under the same name:

- `LATEST_PROTOCOL_VERSION` was `"2025-11-25"`, the version the v1 client offered in `initialize`. In v2 it is `"2026-07-28"`, the newest revision the SDK speaks, which the `initialize` handshake never negotiates; `from mcp.types import LATEST_PROTOCOL_VERSION` still imports, so the value changes silently. Where your code used it as the handshake version (a hand-built `initialize`, or a comparison against the negotiated version), use `LATEST_HANDSHAKE_VERSION` (`"2025-11-25"`).
- `SUPPORTED_PROTOCOL_VERSIONS` is now a `tuple` (was a `list`) with `"2026-07-28"` appended: membership tests still pass, but `[-1]` is now `"2026-07-28"` and list operations such as `+ [...]` raise `TypeError`. The handshake-only set, with v1's four values, is `HANDSHAKE_PROTOCOL_VERSIONS`.

**Before (v1):**

```python
from mcp.shared.version import LATEST_PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS
```

**After (v2):**

```python
from mcp.types.version import HANDSHAKE_PROTOCOL_VERSIONS, LATEST_HANDSHAKE_VERSION

# LATEST_HANDSHAKE_VERSION == "2025-11-25", the value v1 called LATEST_PROTOCOL_VERSION
```

### `McpError` renamed to `MCPError`

Hard rename, no compatibility alias; import from `mcp` or `mcp.shared.exceptions` as before. `e.error` still holds the `ErrorData`, so `e.error.code`/`e.error.message` keep working; `e.code`, `e.message`, and `e.data` are new shortcuts.

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
from mcp import MCPError

try:
    result = await session.call_tool("my_tool")
except MCPError as e:
    print(f"Error: {e.message}")
```

The constructor now takes `code`, `message`, and optional `data` instead of an `ErrorData` (the v1 form raises `TypeError`). If you already hold an `ErrorData`, use `MCPError.from_error_data(error)`.

**Before (v1):**

```python
from mcp.shared.exceptions import McpError
from mcp.types import INVALID_REQUEST, ErrorData

raise McpError(ErrorData(code=INVALID_REQUEST, message="bad input"))
```

**After (v2):**

```python
from mcp import MCPError
from mcp.types import INVALID_REQUEST

raise MCPError(INVALID_REQUEST, "bad input")
```

## MCPServer (formerly FastMCP)

### `FastMCP` renamed to `MCPServer`

`FastMCP` is now `MCPServer`, and the `mcp.server.fastmcp` subpackage is now `mcp.server.mcpserver` with the same internal layout (the old paths are removed, not deprecated).

**Before (v1):**

```python
from mcp.server.fastmcp import Context, FastMCP

mcp = FastMCP("Demo")
```

**After (v2):**

```python
from mcp.server.mcpserver import Context, MCPServer

mcp = MCPServer("Demo")
```

Other imports move the same way:

- `Image`, `Audio`, `Icon` — from `mcp.server.mcpserver` (`Icon`'s `mimeType` field is now `mime_type`; see [snake_case renames](#field-names-changed-from-camelcase-to-snake_case))
- `Message`, `UserMessage`, `AssistantMessage` — from `mcp.server.mcpserver.prompts.base`
- `ToolError`, `ResourceError`, `MCPServerError` (was `FastMCPError`) — from `mcp.server.mcpserver.exceptions`; `ValidationError` is removed (the SDK never raised it)

The `ctx.fastmcp` property is now `ctx.mcp_server`. Beyond the changes in this group, the `@mcp.tool()`/`@mcp.resource()`/`@mcp.prompt()` decorator surface, handler bodies and their return-value wrapping, the `lifespan=` hook, and `mcp.run()` port with only the import change.

### Default server name and version changed

A nameless `FastMCP()` reported `serverInfo.name == "FastMCP"`; a nameless `MCPServer()` reports `"mcp-server"`. A server without its own version (every v1 `FastMCP`, which had no `version` parameter, and a lowlevel `Server` given none) reported the installed `mcp` package version as `serverInfo.version`; v2 reports an empty string. Nothing raises, but clients keying off `serverInfo` and tests asserting on the initialize result see the new values, so set both explicitly:

**Before (v1):**

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP()  # serverInfo.name == "FastMCP", version == installed mcp version
```

**After (v2):**

```python
from mcp.server import MCPServer

mcp = MCPServer("my-server", version="1.2.3")
```

The lowlevel `Server` takes the same fix: `Server("my-server", version="1.2.3")`.

### `MCPServer` constructor: positional parameter order changed

The positional order is now `name, title, description, instructions, website_url, icons, version` (v1: `name, instructions, website_url, icons`). A v1 call that passed `instructions` as the second positional argument still runs on v2, but the string lands in `title`: the server reports it as `serverInfo.title` and clients receive no `instructions`.

**Before (v1):**

```python
from mcp.server.fastmcp import FastMCP

# Second positional parameter is instructions
mcp = FastMCP("Demo", "You answer questions about the weather.")
```

**After (v2):**

```python
from mcp.server import MCPServer

mcp = MCPServer("Demo", instructions="You answer questions about the weather.")
```

Keep `name` positional and pass everything else by keyword.

### `mount_path` parameter removed from `MCPServer`

`mount_path` is gone from the constructor, `Settings`, `run()`, `run_sse_async()`, and `sse_app()`: passing it raises `TypeError`, and `mcp.settings.mount_path = ...` raises `ValueError`. The SSE transport already prefixes its message endpoint with the ASGI `root_path` that Starlette's `Mount` sets, so delete `mount_path` and mount as before.

**Before (v1):**

```python
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server.fastmcp import FastMCP

github_mcp = FastMCP("GitHub", mount_path="/github")
search_mcp = FastMCP("Search")
search_mcp.settings.mount_path = "/search"
curl_mcp = FastMCP("Curl")

app = Starlette(
    routes=[
        Mount("/github", app=github_mcp.sse_app()),
        Mount("/search", app=search_mcp.sse_app()),
        Mount("/curl", app=curl_mcp.sse_app("/curl")),
    ]
)
```

**After (v2):**

```python
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server import MCPServer

github_mcp = MCPServer("GitHub")
search_mcp = MCPServer("Search")
curl_mcp = MCPServer("Curl")

app = Starlette(
    routes=[
        Mount("/github", app=github_mcp.sse_app()),
        Mount("/search", app=search_mcp.sse_app()),
        Mount("/curl", app=curl_mcp.sse_app()),
    ]
)
```

`mcp.run(transport="sse", mount_path="/x")` becomes `mcp.run(transport="sse")`. See [Add to an existing app](run/asgi.md) for mounting details.

### Transport parameters moved off the `MCPServer` constructor

Transport options are no longer constructor arguments: `MCPServer(..., json_response=True)` raises `TypeError: MCPServer.__init__() got an unexpected keyword argument 'json_response'`. Pass them where the server starts instead: `run(transport, ...)`, or `streamable_http_app(...)` / `sse_app(...)` when you build the ASGI app yourself (same options minus `port`, which belongs to whatever serves the app).

Moved: `host`, `port`, `sse_path`, `message_path`, `streamable_http_path`, `json_response`, `stateless_http`, `max_request_body_size`, `event_store`, `retry_interval`, `transport_security`. `mount_path` is removed, not moved. `json_response=True` and `stateless_http=True` also change how server-to-client requests fail, see [Server-initiated sampling, elicitation, and roots raise `NoBackChannelError`](#server-initiated-sampling-elicitation-and-roots-raise-nobackchannelerror).

**Before (v1):**

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Demo", json_response=True, stateless_http=True)
mcp.run(transport="streamable-http")

# or, for SSE:
mcp = FastMCP("Server", host="0.0.0.0", port=9000, sse_path="/events")
mcp.run(transport="sse")
```

**After (v2):**

```python
from mcp.server import MCPServer

mcp = MCPServer("Demo")
mcp.run(transport="streamable-http", json_response=True, stateless_http=True)

# or, for SSE:
mcp = MCPServer("Server")
mcp.run(transport="sse", host="0.0.0.0", port=9000, sse_path="/events")
```

For a mounted app the options go on the app method: `FastMCP("App", json_response=True).streamable_http_app()` becomes `MCPServer("App").streamable_http_app(json_response=True)` ([Add to an existing app](run/asgi.md)).

The moved fields are gone from `mcp.settings` too: `mcp.settings.port = 9000` now raises `ValueError: "Settings" object has no field "port"`. Nothing on the server object carries transport configuration any more, so if the module that builds the app is not the one that configures the server, carry the keywords yourself, e.g. `build_app = functools.partial(mcp.streamable_http_app, json_response=True)`.

DNS-rebinding protection is now armed from the `host=` these methods receive (default `127.0.0.1`) rather than from the constructor. v1 code that passed `host="0.0.0.0"` or `transport_security=` to `FastMCP(...)` so a mounted or externally-served app accepts a real hostname must pass it at the new call site; otherwise non-localhost `Host` headers are rejected with `421 Invalid Host header`. See [Deploy & scale](run/deploy.md).

### Streamable HTTP: lifespan now entered once at manager startup

Under streamable HTTP, v1 entered the server's `lifespan` for every session (stateful) or every request (`stateless_http=True`) and exited it when that session or request ended. In v2 `StreamableHTTPSessionManager.run()` enters it once at startup, and the object it yields is the same `ctx.request_context.lifespan_context` for every session and request (see [Lifespan](handlers/lifespan.md)). SSE and stdio are unchanged.

State you scoped to a session or request by yielding it from the lifespan (a per-client cache, a per-connection transaction) is now shared between all clients and torn down only at server shutdown. There is no per-session teardown hook: acquire and release such state per call inside the handler, and keep only server-wide resources (connection pool, HTTP client, loaded model) in the lifespan, which need no change.

### `MCPServer.get_context()` removed

`MCPServer.get_context()` is gone; there is no ambient context to fetch. Declare a `ctx: Context` parameter on the handler and the SDK injects it. Injection only happens for the registered function, so helpers that called `get_context()` now take `ctx` as an argument. See [The Context](handlers/context.md).

**Before (v1):**

```python
@mcp.tool()
async def my_tool(x: int) -> str:
    ctx = mcp.get_context()
    await ctx.report_progress(1, 2)
    return str(x)
```

**After (v2):**

```python
from mcp.server.mcpserver import Context

@mcp.tool()
async def my_tool(x: int, ctx: Context) -> str:
    await ctx.report_progress(1, 2)
    return str(x)
```

### Sync handler functions now run on a worker thread

v1 called a synchronous (`def`) tool, resource, or prompt function directly on the event-loop thread. v2 runs it on a worker thread via `anyio.to_thread.run_sync()`; `async def` handlers are unchanged. A synchronous handler that depended on the event-loop thread now behaves differently:

- `asyncio.get_running_loop()` in the body raises `RuntimeError: no running event loop`.
- Thread-affine state (a `sqlite3` connection created at import time, thread locals set at startup) is now used from another thread.
- Concurrent requests to synchronous handlers run in parallel, so unlocked shared state races.

Declare the handler `async def` to keep it on the event-loop thread.

**Before (v1):**

```python
import asyncio

@mcp.tool()
def now_ms() -> int:
    return int(asyncio.get_running_loop().time() * 1000)
```

**After (v2):**

```python
import asyncio

@mcp.tool()
async def now_ms() -> int:
    return int(asyncio.get_running_loop().time() * 1000)
```

### Calling `MCPServer.call_tool()`, `get_prompt()`, and `read_resource()` directly

Direct calls to these methods (unit tests, wrapper servers, a handler that calls another) change in two ways.

**Return types.** `call_tool()` returns a `CallToolResult` instead of a bare list of content blocks or a `(content, structured_content)` tuple, and every declared return type is widened with `InputRequiredResult` (returned only when a [multi-round-trip](handlers/multi-round-trip.md) handler asks the client for input), so narrow with `isinstance`:

**Before (v1):**

```python
# (content, structured_content) tuple for tools with an output schema,
# a bare list of content blocks otherwise
content, structured = await mcp.call_tool("greet", {"name": "Ada"})
text = content[0].text
```

**After (v2):**

```python
from mcp.types import CallToolResult, TextContent

result = await mcp.call_tool("greet", {"name": "Ada"})
assert isinstance(result, CallToolResult)
block = result.content[0]
assert isinstance(block, TextContent)
text = block.text
structured = result.structured_content  # {"result": "Hello, Ada!"}
```

`get_prompt()` is likewise `GetPromptResult | InputRequiredResult` and `read_resource()` is `Iterable[ReadResourceContents] | InputRequiredResult`; runtime behavior is unchanged, but direct calls need the same narrowing (`Prompt.render()` and `ResourceTemplate.create_resource()` widen too). In tests, prefer the in-memory [`Client(mcp)`](get-started/testing.md), whose methods return plain `CallToolResult`/`GetPromptResult`/`ReadResourceResult`.

**No ambient request context.** In v1 these methods read the ambient request context, so calling `mcp.call_tool()` from inside a handler gave the inner handler a working `ctx`. v2 only ever injects a [`Context`](handlers/context.md): each method takes an optional `context: Context | None = None`, and omitting it builds a request-less `Context`, so an inner handler that touches `ctx.session`, `ctx.request_id`, etc. fails with "Context is not available outside of a request". Pass the caller's `ctx` through:

**Before (v1):**

```python
from mcp.server.fastmcp import Context, FastMCP

mcp = FastMCP("Demo")


@mcp.tool()
async def report(ctx: Context) -> str:
    return f"report for request {ctx.request_id}"


@mcp.tool()
async def digest(ctx: Context) -> str:
    result = await mcp.call_tool("report", {})
    return f"digest: {result}"
```

**After (v2):**

```python
from mcp.server import MCPServer
from mcp.server.mcpserver import Context

mcp = MCPServer("Demo")


@mcp.tool()
async def report(ctx: Context) -> str:
    return f"report for request {ctx.request_id}"


@mcp.tool()
async def digest(ctx: Context) -> str:
    result = await mcp.call_tool("report", {}, context=ctx)
    return f"digest: {result}"
```

The lower layers (`ToolManager.call_tool`, `Tool.run`, `Prompt.render`, `ResourceTemplate.create_resource`, `ResourceManager.get_resource`) now require the `context` argument; call the `MCPServer` methods above instead.

### `MCPError` raised from an `@mcp.tool()` handler now surfaces as a JSON-RPC error

Raising `MCPError` (or any subclass) inside an `@mcp.tool()` handler, or letting one propagate from a call the tool makes, now fails the `tools/call` request with a JSON-RPC error carrying the raised `code`, `message`, and `data`, so the client's `call_tool()` raises `MCPError` instead of returning a result. v1 caught it like any other exception and returned `CallToolResult(isError=True)` with the text `Error executing tool <name>: <message>`, dropping the code and `data` (`UrlElicitationRequiredError` was already re-raised and is unchanged).

**Before (v1):**

```python
from mcp.server.fastmcp import FastMCP
from mcp.shared.exceptions import McpError
from mcp.types import INVALID_PARAMS, ErrorData

mcp = FastMCP("demo")


@mcp.tool()
def strict(x: int) -> int:
    if x < 0:
        raise McpError(ErrorData(code=INVALID_PARAMS, message="x must be non-negative"))
    return x

# session.call_tool("strict", {"x": -1}) returned CallToolResult(isError=True)
# with text "Error executing tool strict: x must be non-negative"
```

**After (v2):**

```python
from mcp import Client, MCPError
from mcp.server import MCPServer
from mcp.types import INVALID_PARAMS

mcp = MCPServer("demo")


@mcp.tool()
def strict(x: int) -> int:
    if x < 0:
        raise MCPError(INVALID_PARAMS, "x must be non-negative", {"x": x})
    return x


async def call() -> None:
    async with Client(mcp) as client:
        try:
            await client.call_tool("strict", {"x": -1})
        except MCPError as e:  # was: `if result.isError:`
            print(e.code, e.message, e.data)  # -32602 x must be non-negative {'x': -1}
```

To keep the old model-visible `is_error=True` result, raise a plain exception (any non-`MCPError` still becomes one) or return `CallToolResult(is_error=True, ...)` from the tool. See [Handling errors](servers/handling-errors.md).

### Reading a missing resource raises `ResourceNotFoundError` and returns invalid-params

Reading a URI that matches no resource or template now fails with JSON-RPC code `-32602` (invalid params) and `error.data = {"uri": ...}`, per [SEP-2164](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2164); v1 returned code `0` with no `data`. Other resource read failures now return `-32603` with the same `data` and a generic message instead of the exception text.

Server-side, `MCPServer.read_resource()` and `ctx.read_resource()` raise `ResourceNotFoundError` for an unknown URI and its parent `ResourceError` for a failing template, where v1 raised `ValueError` for both.

**Before (v1):**

```python
try:
    contents = await ctx.read_resource("config://missing")
except ValueError:
    ...
```

**After (v2):**

```python
from mcp.server.mcpserver.exceptions import ResourceNotFoundError

try:
    contents = await ctx.read_resource("config://missing")
except ResourceNotFoundError:
    ...
```

A template handler that raised a plain exception for a missing instance should now raise `ResourceNotFoundError` so its message and the URI reach the client as `-32602`; see [Handling errors](servers/handling-errors.md).

### `Resource` classes reject unknown keyword arguments

The `Resource` base class now sets `extra="forbid"`, so `TextResource`, `BinaryResource`, `FunctionResource`, `FileResource`, `HttpResource`, `DirectoryResource`, and your own subclasses raise `pydantic.ValidationError` on an unrecognised keyword argument instead of silently dropping it. Remove the stray argument; to restore v1's silent-drop behavior on a subclass, set `model_config = ConfigDict(extra="ignore")`.

### `FileResource.is_binary` replaced by `encoding`

`FileResource` no longer takes `is_binary`; passing it raises `pydantic.ValidationError` at construction. Text versus blob is now chosen by `encoding: str | None` (`None` reads bytes and serves a base64 blob). When omitted, `encoding` is derived from `mime_type`: a declared `charset=` wins, otherwise `"utf-8-sig"` (UTF-8, BOM tolerated) for `text/*`, `application/json`, `application/xml` and any `+json`/`+xml` type, and `None` for everything else.

Two defaults change with no edit on your side: files whose mime type is textual but not `text/*` (`application/json`, `application/xml`, `image/svg+xml`, …), which v1 served as blobs, are now served as text; and text files are decoded as UTF-8 instead of with the platform locale encoding (v1 called `Path.read_text()` with no encoding). Where either default is wrong for a file, pass `encoding` explicitly.

**Before (v1):**

```python
from pathlib import Path

from mcp.server.fastmcp.resources import FileResource

FileResource(uri="file:///logo.png", path=Path("/srv/logo.png"), mime_type="image/png", is_binary=True)
FileResource(uri="file:///notes.txt", path=Path("/srv/notes.txt"))  # text, locale encoding
FileResource(uri="file:///data.json", path=Path("/srv/data.json"), mime_type="application/json")  # blob
```

**After (v2):**

```python
from pathlib import Path

from mcp.server.mcpserver.resources import FileResource

FileResource(uri="file:///logo.png", path=Path("/srv/logo.png"), mime_type="image/png")  # blob, from mime_type
FileResource(uri="file:///notes.txt", path=Path("/srv/notes.txt"))  # text, UTF-8
FileResource(uri="file:///data.json", path=Path("/srv/data.json"), mime_type="application/json")  # now text
FileResource(uri="file:///legacy.txt", path=Path("/srv/legacy.txt"), encoding="cp1252")  # non-UTF-8 text
# keep this JSON file as a blob
FileResource(uri="file:///raw.json", path=Path("/srv/raw.json"), mime_type="application/json", encoding=None)
```

### Resource templates: matching behavior changes

Template matching now follows [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570) instead of a regex built from the URI string. Existing `{var}` templates behave differently in these ways:

**Extracted values are percent-decoded.** `docs://{name}` read as `docs://hello%20world` calls the handler with `name = "hello world"`; v1 passed `"hello%20world"`. Because `%2F` decodes to `/`, a simple `{var}` value can now contain slashes (`docs://a%2Fb` gives `name = "a/b"`), which v1's `[^/]+` capture ruled out. Remove any manual `unquote()` in the handler.

**Path-safety checks reject unsafe values by default.** A decoded value that escapes upward through `..` segments (a substring like `v1.0..v2.0` is fine), looks like an absolute path (`/etc/passwd`, `C:\Windows`, any single-letter `x:` prefix), or contains a null byte fails the read with the same `-32602` "Unknown resource" error as an unmatched URI, and the handler never runs. Exempt a parameter that legitimately carries such values, or pass `resource_security=` to `MCPServer` to change the policy server-wide:

```python
from mcp.server.mcpserver import ResourceSecurity

@mcp.resource("inspect://file/{target}", security=ResourceSecurity(exempt_params={"target"}))
def inspect_file(target: str) -> str: ...
```

**Literals and delimiters match exactly.** `data://v1.0/{id}` no longer matches `data://v1X0/42` (a template `.` was regex any-character), and `{var}` no longer captures `?`, `#`, `&`, or `,`: `api://{id}` no longer matches `api://foo?x=1`. To keep accepting the query string, write `api://{id}{?x}` and give the `x` parameter a default.

**`{var}` matches an empty value.** `tickets://{ticket_id}` now matches `tickets://` with `ticket_id=""`; v1 returned "Unknown resource" instead. Validate non-empty values in the handler if you relied on that.

**Templates v1 accepted can now fail at decoration time.** Duplicate variable names and other malformed shapes raise `InvalidUriTemplate` (a `ValueError`) when the decorator runs; v1 raised `re.error` only once a read reached the template. Two adjacent variables (`x://{name}{path}`), which v1's regex accepted, are rejected: separate them with a literal (`x://{name}/{path}`) or capture one variable and split it in the handler. A static URI whose handler takes only a `Context` parameter, silently unreachable in v1, now raises `ValueError` at decoration time: drop the parameter, or add a template variable so `Context` is injected; an optional query variable keeps a plain `notes://recent` read matching:

```python
@mcp.resource("notes://recent{?limit}")
async def recent_notes(ctx: Context, limit: int = 10) -> str: ...
```

See [URI templates and path safety](servers/uri-templates.md) for the operators added in v2 and the security settings.

### `MCPServer`'s `Context` logging: `message` renamed to `data`

On the `MCPServer` `Context`, `log()`, `debug()`, `info()`, `warning()`, and `error()` now take `data: Any` (any JSON-serializable value, so structured payloads go in `data`) instead of `message: str`.

**Before (v1):**

```python
await ctx.log(level="info", message="hello")
```

**After (v2):**

```python
await ctx.log(level="info", data="hello")
await ctx.info({"message": "Connection failed", "host": "localhost", "port": 5432})
```

Positional calls (`await ctx.info("hello")`) and `logger_name=` are unaffected. These methods are also deprecated in v2 and emit `mcp.MCPDeprecationWarning`, so the rename only keeps them working; the durable replacement is standard `logging` (see [Logging](handlers/logging.md) and [Deprecated features](deprecated.md)).

### `Context.client_id` removed

`ctx.client_id` is removed; it only echoed a non-standard `client_id` key from the request's `_meta`. Read that key directly, or use the access token for the authenticated OAuth client (see [Authorization](run/authorization.md#the-callers-identity)).

**Before (v1):**

```python
client_id = ctx.client_id
```

**After (v2):**

```python
from mcp.server.auth.middleware.auth_context import get_access_token

# the raw _meta key, if you set it yourself
meta = ctx.request_context.meta
client_id = meta.get("client_id") if meta else None

# the authenticated OAuth client (usually what you want)
token = get_access_token()
client_id = token.client_id if token else None
```

### `ProgressContext` and `progress()` context manager removed

The `mcp.shared.progress` module (`Progress`, `ProgressContext`, and the `progress()` context manager) is removed. Use `Context.report_progress()` in an `MCPServer` handler, or `ctx.session.report_progress()` in a lowlevel `Server` handler. Two behavior changes:

- `report_progress` takes the absolute current value, not a delta: `p.progress(25)` called twice reported `25` then `50`, while the same calls to `report_progress` report `25` twice. Keep the running total yourself.
- With no progress token on the request, `progress()` raised `ValueError`; `report_progress` is a silent no-op.

**Before (v1):**

```python
from mcp.shared.progress import progress

with progress(request_context, total=100) as p:
    await p.progress(25, message="step 1")  # reports 25
    await p.progress(25)                    # reports 50
```

**After (v2):**

```python
from mcp.server import MCPServer
from mcp.server.mcpserver import Context

mcp = MCPServer("Progress")


@mcp.tool()
async def my_tool(x: int, ctx: Context) -> str:
    await ctx.report_progress(25, 100, message="step 1")
    await ctx.report_progress(50, 100)  # absolute value, not a delta
    return "done"
```

In a lowlevel `Server` handler the equivalent is `await ctx.session.report_progress(50, 100, message="halfway")` on the `ServerRequestContext`. See [Progress](handlers/progress.md).

### `Context.elicit()` rejects non-spec schemas; mismatched answers raise `ValueError`

`ctx.elicit()` (and `elicit_with_validation()`) now reject two field shapes v1 accepted, raising `TypeError` before anything is sent: a `list[str]` field and a union of primitives such as `int | str`. Use `list[Literal[...]]` for a multi-select and a single primitive type per field.

**Before (v1):**

```python
from pydantic import BaseModel


class Preferences(BaseModel):
    tags: list[str]
    level: int | str
```

**After (v2):**

```python
from typing import Literal

from pydantic import BaseModel


class Preferences(BaseModel):
    tags: list[Literal["news", "sports"]]
    level: str
```

An accepted answer whose content doesn't match the schema now raises `ValueError` (the pydantic `ValidationError` is its `__cause__`) instead of letting `ValidationError` propagate; change `except ValidationError` around `ctx.elicit()` to `except ValueError`.

See [Elicitation](handlers/elicitation.md).

### `isinstance()` checks against `ElicitationResult` raise `TypeError`

`ElicitationResult` (the return type of `ctx.elicit()`) is now a subscriptable `TypeAliasType` rather than a plain union, so it is no longer a valid `isinstance()` target. Check the member classes instead (unmoved in `mcp.server.elicitation`), or branch on `result.action` (`"accept"` / `"decline"` / `"cancel"`), which is unaffected.

**Before (v1):**

```python
from mcp.server.elicitation import ElicitationResult

if isinstance(result, ElicitationResult):
    ...
```

**After (v2):**

```python
from mcp.server.elicitation import AcceptedElicitation, CancelledElicitation, DeclinedElicitation

if isinstance(result, (AcceptedElicitation, DeclinedElicitation, CancelledElicitation)):
    ...
```

## Lowlevel Server

### Lowlevel `Server`: decorator-based handlers replaced with constructor `on_*` params

The lowlevel `Server` no longer has `@server.list_tools()`-style registration decorators. Pass each handler to the constructor as an `on_*` keyword argument; every handler has the signature `async (ctx: ServerRequestContext, params) -> Result`, taking the typed params model and returning the full result type.

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
from mcp.types import (
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
    return CallToolResult(content=[TextContent(type="text", text=f"Called {params.name}")])


server = Server("my-server", on_list_tools=handle_list_tools, on_call_tool=handle_call_tool)
```

`ctx.session` is the `ServerSession`; `ctx.lifespan_context`, `ctx.request_id`, and `ctx.meta` are on the context too. The `jsonschema` input/output validation that `@server.call_tool()` performed is gone: `input_schema` is advertised, never applied, so validate `params.arguments` yourself.

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
| `@server.progress_notification()` | `on_progress` | `ProgressNotificationParams` | `None` |
| (none) | `on_ping` | `RequestParams \| None` | `EmptyResult` |
| (none) | `on_roots_list_changed` | `NotificationParams \| None` | `None` |

All `params` and result types come from `mcp.types`. The full handler model is in [The low-level Server](advanced/low-level-server.md). Around the handlers, the transports and how you drive `server.run(...)`, `create_initialization_options()`, `NotificationOptions`, and the streamable-HTTP session manager with its `EventStore` are unchanged.

### Lowlevel `Server`: automatic return value wrapping removed

The v1 handler decorators converted several return shapes into the wire result type; v2 `on_*` handlers return the fully constructed result (see [The low-level Server](advanced/low-level-server.md)). If you want the conveniences back, use `MCPServer`, whose `@mcp.tool()` and `@mcp.resource()` still wrap return values.

`call_tool` wrapped `list[ContentBlock]`, `dict`, or `(list, dict)` into a `CallToolResult`; a `dict` became `structured_content` plus a JSON `TextContent`. Build it yourself:

**Before (v1):**

```python
@server.call_tool()
async def handle(name: str, arguments: dict) -> dict:
    return {"temperature": 22.5, "city": "London"}
```

**After (v2):**

```python
import json

from mcp.server import ServerRequestContext
from mcp.types import CallToolRequestParams, CallToolResult, TextContent


async def handle(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    data = {"temperature": 22.5, "city": "London"}
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data, indent=2))],
        structured_content=data,
    )
```

`params.arguments` is `None` when the client sends no arguments (the v1 decorator passed `{}`); use `params.arguments or {}`.

`read_resource` converted `Iterable[ReadResourceContents]` (and the deprecated `str`/`bytes` shorthand) into `TextResourceContents`/`BlobResourceContents`, base64-encoding bytes and defaulting the mime type. Build the contents yourself:

**Before (v1):**

```python
from collections.abc import Iterable

from pydantic import AnyUrl

from mcp.server.lowlevel.helper_types import ReadResourceContents


@server.read_resource()
async def handle(uri: AnyUrl) -> Iterable[ReadResourceContents]:
    return [ReadResourceContents(content="file contents", mime_type="text/plain")]
```

**After (v2):**

```python
import base64

from mcp.server import ServerRequestContext
from mcp.types import (
    BlobResourceContents,
    ReadResourceRequestParams,
    ReadResourceResult,
    TextResourceContents,
)


async def handle_read(ctx: ServerRequestContext, params: ReadResourceRequestParams) -> ReadResourceResult:
    if params.uri.endswith(".png"):
        blob = base64.b64encode(b"\x89PNG...").decode()  # base64-encode binary yourself
        return ReadResourceResult(contents=[BlobResourceContents(uri=params.uri, blob=blob, mime_type="image/png")])
    return ReadResourceResult(
        contents=[TextResourceContents(uri=params.uri, text="file contents", mime_type="text/plain")]
    )
```

The other decorators wrapped bare returns too: `list_*` handlers now return `ListToolsResult(tools=[...])`, `ListResourcesResult(resources=[...])`, `ListResourceTemplatesResult(resource_templates=[...])`, and `ListPromptsResult(prompts=[...])`, and `completion` returns `CompleteResult(completion=Completion(values=[...]))` instead of `Completion | None`.

### Lowlevel `Server`: tool handler exceptions no longer become `CallToolResult(is_error=True)`

The v1 `@server.call_tool()` decorator caught any exception the handler raised and returned it as `CallToolResult(isError=True)`, so the model saw the error text and could retry. The v2 `on_call_tool` handler has no such wrapper: the exception fails the whole `tools/call` request with a JSON-RPC error instead of a result, the client raises `MCPError`, and the model gets no tool result.

**Before (v1):**

```python
@server.call_tool()
async def call_tool(name: str, arguments: dict):
    raise ValueError("kaboom")  # client received CallToolResult(isError=True)
```

**After (v2):** catch the exception in the handler and build the error result yourself:

```python
from mcp.server import ServerRequestContext
from mcp.types import CallToolRequestParams, CallToolResult, TextContent


async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    try:
        args = params.arguments or {}
        text = str(args["a"] + args["b"])  # tool logic that may raise
    except Exception as e:  # what the v1 decorator did for you
        return CallToolResult(content=[TextContent(type="text", text=str(e))], is_error=True)
    return CallToolResult(content=[TextContent(type="text", text=text)])
```

Raise `MCPError` only when the request itself should fail as a protocol error. If you want the automatic conversion back, `MCPServer`'s `@mcp.tool()` still turns handler exceptions into `is_error=True` results; see [Handling errors](servers/handling-errors.md).

### Lowlevel `Server`: constructor parameters are now keyword-only

All parameters after `name` are now keyword-only, so passing `version` (or anything else) positionally raises `TypeError` at construction:

```python
from mcp.server import Server

# Before (v1)
server = Server("my-server", "1.0")

# After (v2)
server = Server("my-server", version="1.0")
```

### Lowlevel `Server`: type parameter reduced from 2 to 1

`Server[LifespanResultT, RequestT]` is now `Server[LifespanResultT]`. Drop the second type argument; a two-argument subscript fails type checking and raises `TypeError` wherever the subscript is evaluated at runtime (a module-level annotation on Python 3.13 or earlier, a subclass base, `get_type_hints`).

**Before (v1):**

```python
from typing import Any

from mcp.server import Server

server: Server[dict[str, Any], Any] = Server("my-server")
```

**After (v2):**

```python
from typing import Any

from mcp.server import Server

server: Server[dict[str, Any]] = Server("my-server")
```

The transport request object that `RequestT` typed (`server.request_context.request` in v1) is now typed on the handler's `ctx: ServerRequestContext[LifespanContextT, RequestT]`; see [`RequestContext` type parameters simplified](#requestcontext-type-parameters-simplified).

### Lowlevel `Server`: `request_handlers` and `notification_handlers` attributes removed

The public `server.request_handlers` and `server.notification_handlers` dicts are gone. Register handlers after construction with `add_request_handler` / `add_notification_handler`, and look them up with `get_request_handler` / `get_notification_handler`, which return the registered entry (with `.handler` and `.params_type`) or `None`. Keys are method strings, not request types.

**Before (v1):**

```python
from mcp.types import ListToolsRequest

server.request_handlers[ListToolsRequest] = handle_list_tools
if ListToolsRequest in server.request_handlers:
    ...
```

**After (v2):**

```python
from mcp.types import PaginatedRequestParams

server.add_request_handler("tools/list", PaginatedRequestParams, handle_list_tools)
if server.get_request_handler("tools/list") is not None:
    ...
```

`handle_list_tools` uses the v2 `(ctx, params)` handler signature; see [The low-level Server](advanced/low-level-server.md) for `add_request_handler` and custom methods.

### Lowlevel `Server.run(raise_exceptions=True)`: transport errors no longer re-raised

`raise_exceptions=True` now only affects handler exceptions: an unexpected exception from a handler still propagates out of `run()`, but the JSON-RPC error response is written to the client first (v1 re-raised without responding).

Exceptions the transport places on the read stream (e.g. a stdio JSON parse error) are now debug-logged and dropped regardless of the flag: `run()` keeps serving instead of raising, and the client no longer receives the `Internal Server Error` `notifications/message` log entry v1 sent.

### Cancelled requests are no longer answered

v1 answered a request the peer cancelled with a JSON-RPC error, `{"code": 0, "message": "Request cancelled"}`; v2 sends no response at all (no result, no error) on both seats (the server for a cancelled client request, the client for a cancelled server-initiated request such as sampling or elicitation). The one exception is the 2025-era streamable HTTP server transport, whose wire can end a request's stream only with a response: it terminates a cancelled request with `-32800` (`mcp.server.streamable_http.REQUEST_CANCELLED`) instead of the old `0`.

Callers that abandon a call through the SDK (cancelling the awaiting task or scope, or a per-request timeout) are unaffected. Code that hand-sends `notifications/cancelled` while another task still awaits the call breaks: that call no longer raises `McpError("Request cancelled")` and instead waits indefinitely (over 2025-era streamable HTTP it fails with `-32800`). Cancel the scope or task awaiting the call instead; v2 sends `notifications/cancelled` for you and the server interrupts the handler:

**Before (v1):**

```python
await session.send_notification(
    types.ClientNotification(
        types.CancelledNotification(
            params=types.CancelledNotificationParams(requestId=request_id, reason="user aborted"),
        )
    )
)  # the task awaiting session.call_tool(...) then raised McpError("Request cancelled")
```

**After (v2):**

```python
with anyio.CancelScope() as scope:  # abort with scope.cancel(); v2 sends notifications/cancelled for the call
    result = await session.call_tool("slow", {})
if scope.cancelled_caught:
    ...  # the call was abandoned (replaces v1's `except McpError`)
```

### `Server.run()` no longer takes a `stateless` flag

Delete the argument: passing `stateless=` to the lowlevel `Server.run()` raises `TypeError`. Statelessness is configured on the HTTP transport, not per connection:

```python
# Before (v1)
await server.run(read_stream, write_stream, init_options, stateless=True)
```

```python
# After (v2)
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

app = server.streamable_http_app(stateless_http=True)  # the lowlevel Server now builds the ASGI app
# or, driving the session manager yourself (unchanged from v1):
manager = StreamableHTTPSessionManager(app=server, stateless=True)
```

On a `stateless_http=True` server, server-initiated requests (sampling, elicitation, roots) no longer stall waiting for a reply that can never arrive, as they did in v1; they raise `NoBackChannelError` — see [Server-initiated sampling, elicitation, and roots raise `NoBackChannelError`](#server-initiated-sampling-elicitation-and-roots-raise-nobackchannelerror) and [Serving legacy clients](run/legacy-clients.md).

### Lowlevel `Server`: `request_context` property removed

`server.request_context` and the module-level `request_ctx` contextvar are gone. The request context is now the handler's first argument, `ctx: ServerRequestContext`, with the same `session`, `lifespan_context`, `request_id`, `meta`, and `request` fields. There is no ambient accessor in v2, so pass `ctx` down to any helper that called `request_ctx.get()`.

**Before (v1):**

```python
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.server import request_ctx

server = Server("my-server")


@server.call_tool()
async def query_db(name: str, arguments: dict) -> list[types.TextContent]:
    ctx = server.request_context  # or, from any nested helper, request_ctx.get()
    db = ctx.lifespan_context["db"]
    return [types.TextContent(type="text", text=f"queried {db}")]
```

**After (v2):**

```python
from mcp.server import Server, ServerRequestContext
from mcp.types import CallToolRequestParams, CallToolResult, TextContent


async def query_db(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    db = ctx.lifespan_context["db"]
    return CallToolResult(content=[TextContent(type="text", text=f"queried {db}")])


server = Server("my-server", on_call_tool=query_db)
```

See [Low-level server](advanced/low-level-server.md) for the handler shape and `ctx` fields.

### `RequestContext` type parameters simplified

`mcp.shared.context.RequestContext[SessionT, LifespanContextT, RequestT]` is gone (`from mcp.shared.context import RequestContext` raises `ImportError`). It is split by side, and the leading session type parameter is dropped:

- Client callbacks (`sampling`, `elicitation`, `list_roots`) receive the non-generic `ClientRequestContext` from `mcp.client` (`session`, `request_id`, `meta`); the always-`None` `lifespan_context` and `request` are gone.
- Server-side code uses `ServerRequestContext[LifespanContextT, RequestT]` from `mcp.server`.
- The injected high-level `Context[ServerSessionT, LifespanContextT, RequestT]` becomes `Context[LifespanContextT, RequestT]`: `Context[ServerSession, None]` becomes bare `Context`, and `Context[ServerSession, AppContext]` becomes `Context[AppContext]` (a [tools-only](handlers/lifespan.md) spelling, as in v1).

A leftover two-argument `Context[ServerSession, AppContext]` still runs but types `lifespan_context` as `ServerSession`; three type arguments raise `TypeError`.

**Before (v1):**

```python
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, types
from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext


@dataclass
class AppContext:
    db_url: str


async def handle_sampling(
    context: RequestContext[ClientSession, None], params: types.CreateMessageRequestParams
) -> types.CreateMessageResult: ...


def db_url_from(ctx: RequestContext[ServerSession, AppContext, Any]) -> str:
    return ctx.lifespan_context.db_url


async def typed_tool(ctx: Context[ServerSession, AppContext]) -> str:
    return ctx.request_context.lifespan_context.db_url
```

**After (v2):**

```python
from dataclasses import dataclass

from mcp.client import ClientRequestContext
from mcp.server import ServerRequestContext
from mcp.server.mcpserver import Context
from mcp.types import CreateMessageRequestParams, CreateMessageResult


@dataclass
class AppContext:
    db_url: str


async def handle_sampling(
    context: ClientRequestContext, params: CreateMessageRequestParams
) -> CreateMessageResult: ...


def db_url_from(ctx: ServerRequestContext[AppContext]) -> str:
    return ctx.lifespan_context.db_url


async def typed_tool(ctx: Context[AppContext]) -> str:
    return ctx.request_context.lifespan_context.db_url
```

`isinstance(ctx, RequestContext)` checks must name the concrete class, and the `LifespanContextT`/`RequestT` TypeVars now live in `mcp.server.context`. `ServerRequestContext.request_id` is `RequestId | None` (`None` when the same context reaches a notification handler), so code passing `ctx.request_id` on as a definite `RequestId` needs a `None` check.

### `ServerSession` is now a thin proxy (no longer a `BaseSession`)

`ServerSession` no longer subclasses `BaseSession` and is not an async context manager; handlers still reach it as `ctx.session`. The typed helpers (`send_*`, `create_message`, `elicit_*`, `list_roots`, `client_params`, `check_client_capability`) keep their v1 names, but `send_notification` and `send_request` now take the message model itself: the `types.ServerNotification(...)` / `types.ServerRequest(...)` wrappers are gone (see [Replace `RootModel` by union types with `TypeAdapter` validation](#replace-rootmodel-by-union-types-with-typeadapter-validation)).

Two behavior changes reach code that only used `ctx.session`:

- **`ctx.session` is a new object on every request.** v1 kept one `ServerSession` per connection, so servers keyed per-client state on its identity (`WeakKeyDictionary[ServerSession, ...]`, `id(ctx.session)`, a set of captured sessions to notify later). Those idioms now silently misbehave: a session-keyed dict never finds an earlier entry, and a broadcast set gains a proxy per request and sends duplicates. Key on something connection-stable instead: on stateful streamable HTTP the `mcp-session-id` header (`ctx.headers` on `MCPServer`, `ctx.request.headers` in a lowlevel handler); on stdio the process serves a single client.
- **Sends on a closed connection are dropped instead of raising.** In v1 the notification helpers (`send_resource_updated()`, `send_tool_list_changed()`, ...) raised `anyio.ClosedResourceError` / `anyio.BrokenResourceError` once the connection was gone, and broadcast loops used that to prune dead sessions. In v2 the send returns normally (the drop is debug-logged); probe with a request instead: `await session.send_ping()` raises `MCPError` (`CONNECTION_CLOSED`) once the connection has closed. On a 2026-07-28 connection `send_ping()` raises `NoBackChannelError` regardless (see [Behavior changes on v2's default connection](#behavior-changes-on-v2s-default-connection)), so it is a liveness probe only for 2025-11-25 and earlier peers.

If you constructed or subclassed `ServerSession` directly, hand the streams to a `Server` instead:

**Before (v1):**

```python
import anyio

from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.server.stdio import stdio_server
from mcp.types import ServerCapabilities

init_options = InitializationOptions(server_name="mcp", server_version="0.1.0", capabilities=ServerCapabilities())


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        async with ServerSession(read_stream, write_stream, init_options) as session:
            async for message in session.incoming_messages:
                ...


anyio.run(main)
```

**After (v2):**

```python
import anyio

from mcp.server import Server
from mcp.server.stdio import stdio_server

server = Server("mcp")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


anyio.run(main)
```

Register handlers via the `Server` constructor's `on_*` arguments (or `add_request_handler`); to observe every inbound request and notification (what `incoming_messages` or an overridden `_receive_loop` / `_received_request` gave you), add a [middleware](advanced/middleware.md). Also removed from `mcp.server.session`: `InitializationState`, `ServerRequestResponder`, and the `ServerSessionT` TypeVar (see [`RequestContext` type parameters simplified](#requestcontext-type-parameters-simplified)); the tasks-only `experimental`, `send_message()`, and `add_response_router()` members went with the [experimental tasks API](#experimental-tasks-support-removed).

### `ServerSession.elicit()` and `elicit_form()` take `requested_schema`, not `requestedSchema`

The schema parameter of `ServerSession.elicit()` and `ServerSession.elicit_form()` was renamed from `requestedSchema` to `requested_schema`. Unlike the model-field renames, a method parameter has no alias fallback: keyword callers get `TypeError: ServerSession.elicit_form() got an unexpected keyword argument 'requestedSchema'` at call time.

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

Positional callers (`session.elicit_form(message, schema)`) are unaffected. `elicit_url()` already used snake_case parameters in v1.

## Clients

### `ClientSession.get_server_capabilities()` replaced by properties

`get_server_capabilities()` is removed; read the `server_capabilities` property, which is likewise `None` until the session is initialized. `server_info`, `instructions`, and `protocol_version` are exposed the same way, so code that captured the `initialize()` return value only to keep those fields no longer needs to (`initialize()` still returns the `InitializeResult`).

**Before (v1):**

```python
init = await session.initialize()  # captured for serverInfo / instructions / protocolVersion
capabilities = session.get_server_capabilities()
```

**After (v2):**

```python
await session.initialize()
capabilities = session.server_capabilities
server_info = session.server_info
instructions = session.instructions
version = session.protocol_version
```

The high-level [`Client`](client/index.md) exposes the same four properties, populated on entering its `async with` block.

### `cursor` parameter removed from `ClientSession` list methods

`ClientSession.list_resources()`, `list_resource_templates()`, `list_prompts()`, and `list_tools()` no longer accept the deprecated `cursor` argument; passing it raises `TypeError`. Wrap the cursor in `PaginatedRequestParams`, or use the high-level `Client`, whose `list_*` methods take `cursor=` directly (and do not accept `params=`). See [Pagination](advanced/pagination.md).

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

# or, on the high-level Client:
result = await client.list_resources(cursor="next_page_token")
result = await client.list_tools(cursor="next_page_token")
```

### `args` parameter removed from `ClientSessionGroup.call_tool()`

Calls using the old `args=` keyword now raise `TypeError`. Use `arguments=`, or pass the dict positionally (works on both v1 and v2).

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

Replace `timedelta(...)` with plain seconds, or append `.total_seconds()`. Only `StreamableHttpParameters` fails loudly on a leftover `timedelta` (pydantic `ValidationError: Input should be a valid number`); the session and per-call parameters accept it silently, and the first request that arms the timeout raises `TypeError: unsupported operand type(s) for +: 'float' and 'datetime.timedelta'` from anyio. Bare numbers already passed to v1's `StreamableHttpParameters` (which coerced them to `timedelta`) need no change.

### Client request timeouts raise `REQUEST_TIMEOUT` instead of code `408`

A request that exceeds `read_timeout_seconds` still raises `MCPError` (v1's `McpError`), but its error code changed from the HTTP status `408` (`httpx.codes.REQUEST_TIMEOUT`) to the JSON-RPC code `-32001`, exported as `REQUEST_TIMEOUT`. The message wording changed too and differs between the in-process and wire transports, so match on the code, not the text. A leftover `e.error.code == 408` check still evaluates without error and silently never matches.

**Before (v1):**

```python
from mcp.shared.exceptions import McpError

try:
    result = await session.call_tool("slow_tool", {})
except McpError as e:
    if e.error.code == 408:
        ...  # retry / back off
    else:
        raise
```

**After (v2):**

```python
from mcp.shared.exceptions import MCPError
from mcp.types import REQUEST_TIMEOUT  # -32001

try:
    result = await session.call_tool("slow_tool", {})
except MCPError as e:
    if e.code == REQUEST_TIMEOUT:  # e.error.code still works too
        ...  # retry / back off
    else:
        raise
```

### `ClientSession` now runs on `JSONRPCDispatcher`; `BaseSession` removed

`ClientSession` no longer subclasses `BaseSession`: the `mcp.shared.session` module (`BaseSession`, `RequestResponder`) is gone with no shim, and the receive loop is now `JSONRPCDispatcher` (`mcp.shared.jsonrpc_dispatcher`). The constructor callbacks and lifecycle are unchanged (this group's other sections cover the changed parameters and removed methods); code that reached into `BaseSession` to intercept the wire passes a dispatcher through the new keyword-only `dispatcher=` argument instead (the `Dispatcher` protocol in `mcp.shared.dispatcher` is provisional). `ProgressFnT` moved to `mcp.shared.dispatcher`, `RequestId` comes from `mcp.types`, and the session TypeVars (`SendRequestT` and friends) went with the module: the sessions are no longer generic.

`message_handler` no longer receives requests (the typed callbacks answer them): its parameter is `IncomingMessage = ServerNotification | Exception`, exported from `mcp.client` (see [Callbacks](client/callbacks.md)). Notifications arrive as the concrete model rather than the v1 `RootModel` wrapper, so drop `.root` (`message.params`, not `message.root.params`; see [Replace `RootModel` by union types with `TypeAdapter` validation](#replace-rootmodel-by-union-types-with-typeadapter-validation)).

**Before (v1):**

```python
import mcp.types as types
from mcp.shared.session import RequestResponder


async def message_handler(
    message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
) -> None:
    if isinstance(message, Exception):
        raise message
```

**After (v2):**

```python
from mcp.client import IncomingMessage


async def message_handler(message: IncomingMessage) -> None:
    if isinstance(message, Exception):
        raise message
```

Behavior changes on unchanged session code:

- **Callbacks and notifications run concurrently.** v1 handled one inbound message at a time, so callbacks ran inline and in order; v2 runs each server-initiated request callback and each notification delivery in its own task. They may interleave, a callback may itself send requests (that deadlocked in v1), an in-flight callback is interrupted when the server sends `notifications/cancelled`, and a `progress_callback` may run after its request has returned. A raising `message_handler` is now logged instead of ending the receive loop, so the `raise message` idiom above no longer tears the session down. Callbacks that need strict ordering must coordinate themselves.
- **A raising request callback** is answered with `code=0` and the exception text; v1 flattened every callback exception to `INVALID_PARAMS` (`"Invalid request parameters"`, still the answer for a pydantic `ValidationError`). Return `ErrorData` or raise `MCPError` to choose the error code.
- **`send_request` before entering the context manager raises `RuntimeError`** (v1 wrote the request and hung until the read timeout, if any); after the connection has closed it raises `MCPError` (`CONNECTION_CLOSED`) instead of `anyio.ClosedResourceError`.
- **`send_notification` after the connection has closed is dropped with a debug log** (`send_roots_list_changed()` included) instead of raising `anyio.ClosedResourceError`; if that exception was your disconnect signal, probe with a request instead (`send_request` still raises `MCPError` after close).
- **`send_notification` no longer takes `related_request_id`.**
- **Abandoning a request now sends `notifications/cancelled`.** Cancelling the awaiting task or scope, or a request hitting its read timeout, tells the server to interrupt the handler; v1 sent nothing. A cancelled peer no longer answers at all: see [Cancelled requests are no longer answered](#cancelled-requests-are-no-longer-answered).
- **Request callbacks receive `mcp.client.ClientRequestContext`** in place of `RequestContext[ClientSession, Any]`; see [`RequestContext` type parameters simplified](#requestcontext-type-parameters-simplified).

### Experimental Tasks support removed

The deprecated experimental Tasks API is removed (the 2026-07-28 spec moves Tasks into an extension, [SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2663), that this SDK does not implement). The `mcp.client.experimental`, `mcp.server.experimental`, `mcp.shared.experimental`, and `mcp.server.lowlevel.experimental` modules are gone, along with the `experimental` accessors on `Server`, `ServerSession`, `ClientSession`, and `RequestContext`, and the `ClientSession(experimental_task_handlers=...)` argument. The `Task*` models stay in `mcp.types` as types-only definitions; the `TASK_*` constants and the `TaskExecutionMode` alias are gone (see [Removed type aliases and classes](#removed-type-aliases-and-classes)).

There is no drop-in replacement for the tasks runtime (`server.experimental.enable_tasks()` and its `@server.experimental.*` handler decorators, `ctx.experimental.run_task()`, `ServerTaskContext` / `TaskStore`, the client's `session.experimental.call_tool_as_task()` / `poll_task()` / `get_task_result()`). Port by what the code used tasks for:

**Status updates on a long-running tool.** Run the work inline in the handler and replace `task.update_status()` with `ctx.report_progress()` (`ctx.session.report_progress()` in a lowlevel handler); the client passes `progress_callback=` to `call_tool()` instead of creating a task and polling — see [Progress](handlers/progress.md).

**Before (v1):**

```python
async def work(task: ServerTaskContext) -> CallToolResult:
    await task.update_status("Processing step 1...")
    ...

result = await ctx.experimental.run_task(work)

# client: create the task, poll its status, then fetch the result
result = await session.experimental.call_tool_as_task("long_running_task", arguments={}, ttl=60000)
async for status in session.experimental.poll_task(result.task.taskId):
    print(status.statusMessage)
task_result = await session.experimental.get_task_result(result.task.taskId, CallToolResult)
```

**After (v2):**

```python
@mcp.tool()
async def long_running_task(ctx: Context) -> str:
    await ctx.report_progress(1, total=3, message="Processing step 1...")
    ...
    return "Task completed!"

# client
async def on_progress(progress: float, total: float | None, message: str | None) -> None:
    print(message)

result = await client.call_tool("long_running_task", {}, progress_callback=on_progress)
```

**User input mid-work** (`task.elicit()`, `task.create_message()`). Don't port to inline `ctx.elicit()` / `ctx.session.create_message()`: those raise `NoBackChannelError` on 2026-07-28 connections, the default for an in-process `Client(server)`. Use the resolver dependencies (`Elicit`, `Sample`) or return an `InputRequiredResult` — see [Multi-round-trip requests](handlers/multi-round-trip.md) and [Server-initiated sampling, elicitation, and roots raise `NoBackChannelError`](#server-initiated-sampling-elicitation-and-roots-raise-nobackchannelerror).

**Detached work** (fetch the result on a later connection or after a client restart) has no v2 equivalent.

Also drop `execution=ToolExecution(taskSupport=types.TASK_REQUIRED)` from lowlevel `types.Tool` definitions: the constant is gone and nothing in v2 reads the field.

## Transports

Server-side transport entry points (`stdio_server()`, `SseServerTransport`, `StreamableHTTPSessionManager`) keep their v1 import paths and signatures, so apart from [`stdio_server` keeps the protocol streams on private descriptors](#stdio_server-keeps-the-protocol-streams-on-private-descriptors) the sections below are client-side; the streamable-HTTP lifespan change sits under MCPServer ([lifespan entered once at manager startup](#streamable-http-lifespan-now-entered-once-at-manager-startup)).

### `streamablehttp_client` removed

The deprecated `streamablehttp_client` function is gone. Use `streamable_http_client(url, *, http_client=None, terminate_on_close=True)`: headers, timeouts, and auth move onto an `httpx2.AsyncClient` you pass as `http_client` (see [Client transports](client/transports.md)), and the yielded tuple drops the `get_session_id` callback (next section).

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
import httpx2
from mcp.client.streamable_http import streamable_http_client

async with httpx2.AsyncClient(
    headers={"Authorization": "Bearer token"},
    timeout=httpx2.Timeout(30, read=300),
    auth=my_auth,
    follow_redirects=True,
) as http_client:
    async with streamable_http_client(
        url="http://localhost:8000/mcp",
        http_client=http_client,
    ) as (read_stream, write_stream):
        ...
```

Port `timeout=`/`sse_read_timeout=` as `httpx2.Timeout(timeout, read=sse_read_timeout)` and keep `follow_redirects=True`: a bare `httpx2.AsyncClient()` defaults to a flat 5-second timeout (too short for the long-lived GET stream) and no redirect following, while omitting `http_client` gives you a default client with the v1 values (`Timeout(30, read=300)`, redirects followed). `httpx_client_factory` is gone: call your factory yourself, enter the client it returns (the SDK no longer closes a client it did not create), and pass it as `http_client`.

### `get_session_id` callback removed from `streamable_http_client`

`streamable_http_client` now yields `(read_stream, write_stream)` instead of a 3-tuple: the `get_session_id` callback, the `StreamableHTTPTransport.get_session_id()` method behind it, and the `GetSessionIdCallback` alias are gone (`from mcp.client.streamable_http import GetSessionIdCallback` raises `ImportError`; inline `Callable[[], str | None]` if you still need the type).

**Before (v1):**

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async with streamable_http_client(url) as (read_stream, write_stream, get_session_id):
    async with ClientSession(read_stream, write_stream) as session:
        await session.initialize()
        session_id = get_session_id()
```

**After (v2):** unpack two values. If you still need the session ID, read the `mcp-session-id` response header with an `httpx2` event hook (the hook fires on every response; the last entry is the current session's ID):

```python
import httpx2

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

captured_session_ids: list[str] = []


async def capture_session_id(response: httpx2.Response) -> None:
    session_id = response.headers.get("mcp-session-id")
    if session_id:
        captured_session_ids.append(session_id)


http_client = httpx2.AsyncClient(event_hooks={"response": [capture_session_id]}, follow_redirects=True)

async with http_client:
    async with streamable_http_client(url, http_client=http_client) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            session_id = captured_session_ids[-1] if captured_session_ids else None
```

### `StreamableHTTPTransport` parameters removed

`StreamableHTTPTransport` now takes only `url`; passing `headers`, `timeout`, `sse_read_timeout`, or `auth` raises `TypeError`. Configure them on the `httpx2.AsyncClient` you pass to `streamable_http_client(url, http_client=...)` (`headers=`, `auth=`, `timeout=httpx2.Timeout(timeout, read=sse_read_timeout)`), as shown in [`streamablehttp_client` removed](#streamablehttp_client-removed) and [Client transports](client/transports.md). `sse_client` keeps all four parameters; there only `auth` is retyped, to `httpx2.Auth` (see [the `httpx2` swap](#httpx-and-httpx-sse-replaced-by-httpx2)).

### `StreamableHTTPTransport.protocol_version` and `MCP_PROTOCOL_VERSION` removed

`StreamableHTTPTransport` no longer exposes a `protocol_version` attribute; read the negotiated version from [`session.protocol_version` or `client.protocol_version`](#clientsessionget_server_capabilities-replaced-by-properties). The header-name constant moved from `mcp.client.streamable_http` to `mcp.shared.inbound` under a new name (same value, `"mcp-protocol-version"`):

**Before (v1):**

```python
from mcp.client.streamable_http import MCP_PROTOCOL_VERSION

headers = {MCP_PROTOCOL_VERSION: "2025-11-25"}
```

**After (v2):**

```python
from mcp.shared.inbound import MCP_PROTOCOL_VERSION_HEADER

headers = {MCP_PROTOCOL_VERSION_HEADER: "2025-11-25"}
```

### Streamable HTTP: non-2xx responses now surface as per-request JSON-RPC errors

In v1 a 404 to a request POST injected `McpError` with the positive literal code `32600`; any other non-2xx response raised `httpx.HTTPStatusError`, which escaped `streamable_http_client` as an `ExceptionGroup` and cancelled every pending request. In v2 the transport resolves the failing request with a JSON-RPC error, raised as `MCPError` from that one call, and the connection stays usable.

| Server response | v1 | v2 |
| --- | --- | --- |
| 404, session established | `McpError` with positive code `32600` | `MCPError(-32600, 'Session terminated')` |
| 404, no session yet | `McpError` with positive code `32600` | `MCPError(-32601, 'Not Found')` |
| Any other 4xx/5xx | `httpx.HTTPStatusError` escapes the context as `ExceptionGroup` | `MCPError(-32603, 'Server returned an error response')` |
| Any of the above with a JSON-RPC error body | body ignored | body's error surfaced verbatim; an SDK server's expired-session 404 arrives as `MCPError(-32600, 'Session not found')` |

Two v1 patterns silently stop working: an `except* httpx.HTTPStatusError` around the transport context is dead code, and a session-expiry check on `error.code == 32600` never matches the now-negative `-32600`.

**Before (v1):**

```python
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError

try:
    async with streamable_http_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                await session.list_tools()
            except McpError as exc:
                if exc.error.code == 32600:  # 404: "Session terminated"
                    ...  # rebuild the connection
                else:
                    raise
except* httpx.HTTPStatusError:
    ...  # any other 4xx/5xx: rebuild the connection
```

**After (v2):**

```python
from mcp import ClientSession, MCPError
from mcp.client.streamable_http import streamable_http_client
from mcp.types import INVALID_REQUEST  # -32600

async with streamable_http_client(url) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        try:
            await session.list_tools()
        except MCPError as exc:
            if exc.code == INVALID_REQUEST and exc.message in ("Session not found", "Session terminated"):
                ...  # session expired: rebuild the connection
            else:
                raise  # only this call failed; the session is still usable
```

Catch `MCPError` per call ([`McpError` renamed to `MCPError`](#mcperror-renamed-to-mcperror)); connect-level failures such as `httpx2.ConnectError` still escape the transport context as an `ExceptionGroup`, so keep context-level handling for those only. Troubleshooting covers [`Server returned an error response`](troubleshooting.md#mcperror-server-returned-an-error-response) and [`Session not found`](troubleshooting.md#mcperror-session-not-found).

### `mcp.os.win32.utilities` process helpers changed

`mcp.os.win32.utilities` is internal plumbing for `stdio_client`, but code that reused its helpers (e.g. a copy of the stdio client's cleanup) needs two edits: the deprecated `terminate_windows_process` is gone with no replacement (`stdio_client` handles termination itself), and `terminate_windows_process_tree` no longer accepts `timeout_seconds` (the argument was already ignored, so drop it).

**Before (v1):**

```python
from mcp.os.win32.utilities import terminate_windows_process_tree

await terminate_windows_process_tree(process, timeout_seconds)
```

**After (v2):**

```python
from mcp.os.win32.utilities import terminate_windows_process_tree

await terminate_windows_process_tree(process)
```

### `stdio_server` keeps the protocol streams on private descriptors

A POSIX watchdog thread that polls fd 0 to detect a vanished client stops working: while `stdio_server()` (and so any stdio `MCPServer`) is serving, the protocol runs on private duplicates of the standard descriptors, with fd 0 pointing at the null device and fd 1 at stderr (both restored on exit), so the null device never reports `POLLHUP` or `POLLERR` and always polls readable, a hangup wait blocks forever, and an any-event wait fires at startup. Poll a duplicate of the descriptor taken before the server starts:

**Before (v1):**

```python
import os
import select
import threading


def watch_stdin() -> None:
    poller = select.poll()
    poller.register(0, select.POLLHUP | select.POLLERR)
    poller.poll()  # blocked until the client closes the pipe
    os._exit(0)


threading.Thread(target=watch_stdin, daemon=True).start()
```

**After (v2):**

```python
import os
import select
import threading

wire = os.dup(0)  # capture the client pipe before stdio_server() diverts fd 0


def watch_stdin() -> None:
    poller = select.poll()
    poller.register(wire, select.POLLHUP | select.POLLERR)
    poller.poll()  # blocked until the client closes the pipe
    os._exit(0)


threading.Thread(target=watch_stdin, daemon=True).start()
```

This also works on v1. If the descriptor cannot be captured before serving begins, watch `os.getppid()` for a change instead: an orphaned server is reparented when its launching parent dies. The redirection also means output flushed to fd 1 while serving (a stray `print()`, an inherited child process) lands on stderr instead of the wire ([Running your server: stdio](run/index.md#stdio)); explicit `stdin=`/`stdout=` streams passed to `stdio_server()` are used as given and not diverted.

### WebSocket transport removed

`mcp.client.websocket.websocket_client`, `mcp.server.websocket.websocket_server`, and the `mcp[ws]` extra are gone (WebSocket was never part of the MCP spec). Use the streamable HTTP transport instead.

**Before (v1):**

```python
from mcp.client.websocket import websocket_client

async with websocket_client("ws://localhost:8000/ws") as (read, write):
    ...
```

**After (v2):**

```python
from mcp.client.streamable_http import streamable_http_client

async with streamable_http_client("http://localhost:8000/mcp") as (read, write):
    ...
```

Or connect with `Client("http://localhost:8000/mcp")` directly. On the server, drop the `websocket_server` ASGI route and mount `streamable_http_app()` (available on `MCPServer` and the lowlevel `Server`), or call `mcp.run(transport="streamable-http")`. See [Client transports](client/transports.md) and [Add to an existing app](run/asgi.md).

## OAuth and server auth

### `RFC7523OAuthClientProvider` and `JWTParameters` removed

`RFC7523OAuthClientProvider` and its `JWTParameters` model are removed from `mcp.client.auth.extensions.client_credentials`. Use `ClientCredentialsOAuthProvider` for a client secret, `PrivateKeyJWTOAuthProvider` for a JWT.

**Before (v1):**

```python
from mcp.client.auth.extensions.client_credentials import JWTParameters, RFC7523OAuthClientProvider

provider = RFC7523OAuthClientProvider(
    server_url=server_url,
    client_metadata=client_metadata,
    storage=storage,
    jwt_parameters=JWTParameters(issuer="my-client-id", subject="my-client-id", jwt_signing_key=key_pem),
)
```

**After (v2):**

```python
from mcp.client.auth.extensions.client_credentials import PrivateKeyJWTOAuthProvider, SignedJWTParameters

provider = PrivateKeyJWTOAuthProvider(
    server_url=server_url,
    storage=storage,
    client_id="my-client-id",
    assertion_provider=SignedJWTParameters(
        issuer="my-client-id", subject="my-client-id", signing_key=key_pem
    ).create_assertion_provider(),
)
```

The provider sends a `client_credentials` grant with `private_key_jwt` client authentication rather than the `jwt-bearer` grant `RFC7523OAuthClientProvider` sent. Relative to `JWTParameters`, `SignedJWTParameters` drops the `jwt_` prefix (`jwt_signing_key` → `signing_key`, `jwt_signing_algorithm` → `signing_algorithm`, `jwt_lifetime_seconds` → `lifetime_seconds`), renames `claims` to `additional_claims`, and has no `audience` (the provider supplies the authorization server's issuer); a prebuilt `JWTParameters(assertion=...)` becomes `assertion_provider=static_assertion_provider(token)`. See [OAuth clients](client/oauth-clients.md#machine-to-machine). For an enterprise ID-JAG `jwt-bearer` grant, use `IdentityAssertionOAuthProvider` ([Identity assertion](client/identity-assertion.md)). The `authorization_code` flow with `private_key_jwt` token-endpoint authentication has no v2 equivalent. The module also stops re-exporting `OAuthTokenError`; import it from `mcp.client.auth`, its home in both versions.

### OAuth metadata URLs no longer gain a trailing slash

`OAuthMetadata`, `ProtectedResourceMetadata`, `OAuthClientMetadata`, and `AuthSettings` now set `url_preserve_empty_path=True`: a path-less URL parsed from a string (constructor argument or wire JSON) keeps its empty path instead of gaining a trailing slash.

```python
from mcp.shared.auth import OAuthClientMetadata

meta = OAuthClientMetadata.model_validate({"redirect_uris": ["http://localhost:8080"]})
print(meta.model_dump(mode="json")["redirect_uris"])
# v1: ['http://localhost:8080/']
# v2: ['http://localhost:8080']
```

The client sends `redirect_uris[0]` verbatim in the `/authorize` and token requests, and authorization servers match redirect URIs by exact string comparison ([RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749) §3.1.2.3). If a v1 run registered such a URI via Dynamic Client Registration (as `http://localhost:8080/`) and your `TokenStorage` still returns that client information, clear it so the client re-registers, or write the URI with an explicit trailing slash. Redirect URIs with a path (`http://localhost:3000/callback`) and values passed as `AnyUrl(...)`/`AnyHttpUrl(...)` objects are unchanged.

Likewise, a path-less string `issuer_url` or `resource_server_url` in `AuthSettings` is now advertised as `https://as.example.com` rather than `https://as.example.com/`; update anything that pinned the old string form.

### OAuth `callback_handler` returns `AuthorizationCodeResult`

The `callback_handler` passed to `OAuthClientProvider` must return an `AuthorizationCodeResult` instead of a `(code, state)` tuple; an unchanged tuple-returning handler crashes the authorization flow (`AttributeError`). Forward the redirect's `iss` parameter as well: the provider now validates it against the authorization server's issuer ([RFC 9207](https://datatracker.ietf.org/doc/html/rfc9207), [SEP-2468](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2468)) and raises `OAuthFlowError` on a mismatch, or on a missing `iss` when the server advertises `authorization_response_iss_parameter_supported`.

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

See [OAuth clients](client/oauth-clients.md) for the full handler contract.

### `scopes=` renamed to `scope=` on the client-credentials providers

`ClientCredentialsOAuthProvider` and `PrivateKeyJWTOAuthProvider` renamed the `scopes` keyword to `scope`; the value is unchanged (a single space-separated string).

**Before (v1):**

```python
provider = ClientCredentialsOAuthProvider(server_url, storage, client_id, client_secret, scopes="read write")
```

**After (v2):**

```python
provider = ClientCredentialsOAuthProvider(server_url, storage, client_id, client_secret, scope="read write")
```

The `client_secret_post` token request body also now carries `client_id` next to `client_secret` ([RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749) §2.3.1), so update any mock authorization server or test that pins the exact form body.

### `timeout` parameter removed from `OAuthClientProvider`

`OAuthClientProvider` no longer accepts a `timeout` argument, and `OAuthContext.timeout` is gone. The value was stored but never read, so dropping it changes no behavior.

**Before (v1):**

```python
provider = OAuthClientProvider(server_url, client_metadata, storage, timeout=120.0)
```

**After (v2):**

```python
provider = OAuthClientProvider(server_url, client_metadata, storage)
```

If you passed `timeout` intending to bound the wait for the user to authorize, apply that bound where you actually wait: in your `redirect_handler`/`callback_handler`, e.g. `with anyio.fail_after(120): ...`.

### Client rejects authorization server metadata with a mismatched `issuer`

`OAuthClientProvider` now requires the authorization server metadata `issuer` to be string-equal to the URL taken from the protected resource metadata's `authorization_servers` list ([RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) section 3.3, [SEP-2468](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2468)). v1 never compared the two, so a pairing that disagrees (even by a trailing slash) authenticated under v1 and now fails discovery. For example, protected resource metadata advertising `"authorization_servers": ["https://as.example.com"]` against authorization server metadata with `"issuer": "https://as.example.com/"` raises:

```text
OAuthFlowError: Authorization server metadata issuer mismatch: https://as.example.com/ != https://as.example.com
```

There is no client-side override; make the two strings identical. If the MCP server also uses this SDK, `AuthSettings(issuer_url=...)` is what it advertises in `authorization_servers`, so set it to exactly the authorization server's `issuer`. See [OAuth metadata URLs no longer gain a trailing slash](#oauth-metadata-urls-no-longer-gain-a-trailing-slash) for how v2 preserves the exact string form of these URLs.

### OAuth client requests `offline_access` and sends `prompt=consent`

Per [SEP-2207](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2207), when the authorization server's metadata lists `offline_access` in `scopes_supported` and the client's `grant_types` include `refresh_token` (the default), the client appends `offline_access` to the requested scope; whenever `offline_access` is in the scope, the authorization request also carries `prompt=consent`. Unchanged v1 code sends a different authorization URL:

**Before (v1):**

```text
https://as.example.com/authorize?...&scope=read
```

**After (v2):**

```text
https://as.example.com/authorize?...&scope=read+offline_access&prompt=consent
```

End users see the provider's consent screen on every authorization instead of being re-authorized silently, the requested scope is broader by `offline_access` (an authorization server that ties refresh tokens to that scope now issues them), and an authorization server that does not allow `offline_access` for the client can fail the flow with `invalid_scope`.

To send the v1 authorization request again, remove the `refresh_token` grant:

```python
from pydantic import AnyUrl

from mcp.shared.auth import OAuthClientMetadata

client_metadata = OAuthClientMetadata(
    client_name="my-client",
    redirect_uris=[AnyUrl("http://localhost:3000/callback")],
    grant_types=["authorization_code"],
)
```

Unlike v1, this also drops `refresh_token` from the Dynamic Client Registration payload, so authorization servers that gate refresh tokens on the registered grants stop issuing them. If `offline_access` is already in the selected scope (from a `WWW-Authenticate` challenge or a `scopes_supported` list), `prompt=consent` is still sent regardless of `grant_types`; there is no separate switch for it.

### Dynamic Client Registration now sends `application_type`

The registration body now always includes `application_type` ([SEP-837](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/837)), defaulting to `"native"` (loopback/`localhost` redirect URIs). A browser-based client served from a non-local host must set `"web"`, or an OIDC authorization server may reject its non-loopback redirect URIs:

```python
from pydantic import AnyUrl

from mcp.shared.auth import OAuthClientMetadata

client_metadata = OAuthClientMetadata(
    redirect_uris=[AnyUrl("https://app.example.com/callback")],
    application_type="web",
)
```

Non-OIDC authorization servers ignore the parameter.

### `OAuthClientInformationFull` no longer subclasses `OAuthClientMetadata`

`OAuthClientMetadata` (the registration request) and `OAuthClientInformationFull` (the registered-client record) are now siblings over a shared `OAuthClientMetadataBase` instead of the record subclassing the request. So `isinstance(client_info, OAuthClientMetadata)` is `False`, a record is not assignable where an `OAuthClientMetadata` is annotated, and `validate_scope()`/`validate_redirect_uri()` exist only on the record. On the record, `client_id` is now required, `token_endpoint_auth_method` widens to `str | None`, and `redirect_uris` is optional (it holds whatever an authorization server echoes). Code that treated a record as a request must name `OAuthClientInformationFull`, or `OAuthClientMetadataBase` where either model is acceptable:

**Before (v1):**

```python
from pydantic import AnyUrl

from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata


def log_registration(metadata: OAuthClientMetadata) -> None:
    print(metadata.client_name, metadata.scope)


client_info = OAuthClientInformationFull(  # client_id defaulted to None
    redirect_uris=[AnyUrl("http://localhost:3000/callback")],
)
log_registration(client_info)  # a record IS-A request
assert isinstance(client_info, OAuthClientMetadata)
```

**After (v2):**

```python
from pydantic import AnyUrl

from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadataBase


def log_registration(metadata: OAuthClientMetadataBase) -> None:  # request or record
    print(metadata.client_name, metadata.scope)


client_info = OAuthClientInformationFull(
    client_id="my-client",  # now required
    redirect_uris=[AnyUrl("http://localhost:3000/callback")],
)
log_registration(client_info)
```

On the server side, a custom `OAuthAuthorizationServerProvider.register_client` behind the SDK's registration endpoint now receives `client_secret_expires_at=0` (RFC 7591's "never expires") rather than `None` when a secret is issued and `ClientRegistrationOptions.client_secret_expiry_seconds` is unset.

### Stricter client authentication at `/token` and `/revoke`

Two behavior changes affect authorization servers embedded via `auth_server_provider=` / `create_auth_routes`.

**Failed client authentication at `/token` returns `invalid_client`.** v1 answered every client-authentication failure at `/token` (unknown `client_id`, missing, wrong, or expired secret) with 401 `unauthorized_client`; v2 sends 401 `invalid_client` ([RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749) §5.2). Update tests, dashboards, or non-SDK clients that match on the error code.

**Before (v1):**

```text
401 {"error":"unauthorized_client","error_description":"Invalid client_id"}
```

**After (v2):**

```text
401 {"error":"invalid_client","error_description":"Invalid client_id"}
```

**Secret-method client records with no stored secret are rejected.** In v1, a client record whose `token_endpoint_auth_method` was `client_secret_post` or `client_secret_basic` but whose `client_secret` was `None` authenticated without a valid secret. v2 rejects it before grant processing: `/token` returns 401 `invalid_client` and `/revoke` returns 401 `unauthorized_client`, both with "Client is registered for secret-based authentication but has no stored secret". Clients registered through `/register` are unaffected (they always receive a secret); hand-provisioned records need a stored secret or a public auth method.

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

**After (v2):**

```python
from mcp.shared.auth import OAuthClientInformationFull

LEGACY_CLIENT = OAuthClientInformationFull(
    client_id="legacy-client",
    token_endpoint_auth_method="none",  # public client, no secret expected
    redirect_uris=["http://localhost:1234/cb"],
)
```

## Stricter protocol validation and wire behavior

### Server handler results are validated against the protocol schema

Server handler results are now validated against the negotiated protocol version's schema before they are sent. A non-conforming result no longer reaches the client: the server logs `handler for '<method>' returned an invalid result` with the pydantic error, and the client gets `-32603` (`INTERNAL_ERROR`, "Handler returned an invalid result"). Validation runs at serialization, not construction, so a bad model still builds and fails only when a handler returns it.

The case most existing code hits is a hand-built `Tool` whose input schema lacks the required `"type": "object"` (schemas generated by `@mcp.tool()` already conform):

**Before (v1):**

```python
from mcp.types import Tool

Tool(name="ping", inputSchema={})
```

**After (v2):**

```python
from mcp.types import Tool

Tool(name="ping", input_schema={"type": "object"})
```

### Client validates inbound traffic against the protocol schema

The client (`Client`, and `ClientSession` beneath it) validates server results against the negotiated protocol version's schema before parsing them. Spec-invalid output that v1's lenient parse accepted now raises `pydantic.ValidationError` from `list_tools()`, `call_tool()`, and the other request methods; for example a tool whose `inputSchema` (or `outputSchema`) is `{}`, since the spec requires `"type": "object"`. There is no opt-out: catch `pydantic.ValidationError` around calls to servers you don't control, or fix the server.

### Every outbound request now carries a `_meta` envelope; OpenTelemetry is on by default

Every request the SDK sends (client-to-server and server-to-client, at every negotiated protocol version) now includes `params._meta`, even where v1 sent no `params` at all. No setting restores the v1 wire shape, so update fixtures, mock servers, and snapshot tests that assert on raw request bytes.

**Before (v1)**, `ClientSession` against a 2025-11-25 peer:

```text
{"method":"ping","jsonrpc":"2.0","id":1}
{"method":"tools/list","jsonrpc":"2.0","id":2}
```

**After (v2)**, the same `ClientSession` code (or `Client(..., mode='legacy')`) against the same peer:

```text
{"jsonrpc":"2.0","id":2,"method":"ping","params":{"_meta":{}}}
{"jsonrpc":"2.0","id":3,"method":"tools/list","params":{"_meta":{}}}
```

The envelope is the carrier for OpenTelemetry trace propagation ([SEP-414](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/414)), which v2 enables by default: every server wraps each inbound message in a span and the client opens a span per outbound request, both under the `mcp-python-sdk` tracer. With no OpenTelemetry SDK configured these are no-ops. If your application already installs a global tracer provider, upgrading starts recording MCP client and server spans and injects a W3C `traceparent` into every outbound `_meta`, propagating your trace ids to the servers you call. To opt out, filter the `mcp-python-sdk` instrumentation scope in your span pipeline, or remove the server middleware as shown in [OpenTelemetry](run/opentelemetry.md); the client-side span and `traceparent` injection have no switch.

## Testing utilities

### `create_connected_server_and_client_session` removed

`mcp.shared.memory.create_connected_server_and_client_session` is gone. `Client` takes the `MCPServer` or lowlevel `Server` instance directly and connects in-process (see [Testing](get-started/testing.md)).

**Before (v1):**

```python
from mcp.shared.memory import create_connected_server_and_client_session

async with create_connected_server_and_client_session(server) as session:
    result = await session.call_tool("my_tool", {"x": 1})
```

**After (v2):**

```python
from mcp import Client

async with Client(server) as client:
    result = await client.call_tool("my_tool", {"x": 1})
```

`Client` accepts the helper's keyword arguments (`sampling_callback`, `list_roots_callback`, `logging_callback`, `message_handler`, `elicitation_callback`, `client_info`, `raise_exceptions`, and `read_timeout_seconds`, now a `float` — see [Timeouts take `float` seconds instead of `timedelta`](#timeouts-take-float-seconds-instead-of-timedelta)). Request methods live on `client`, and `client.session` is the underlying `ClientSession`; `Client`'s `list_*()` methods paginate with `cursor=` rather than `params=PaginatedRequestParams(...)` (see [`cursor` parameter removed from `ClientSession` list methods](#cursor-parameter-removed-from-clientsession-list-methods)).

Unlike the helper, which always ran the pre-2026 `initialize` handshake, `Client(server)` negotiates 2026-07-28 by default, so unchanged sampling, elicitation, logging, and change-notification code behaves differently: see [Behavior changes on v2's default connection](#behavior-changes-on-v2s-default-connection). On that connection `session.send_ping()`, `set_logging_level()`, and `subscribe_resource()`/`unsubscribe_resource()` also raise `MCPError` `-32601` (Method not found), and client-to-server progress notifications are not delivered. `Client(server, mode="legacy")` restores the pre-2026 handshake and all of the above.

`create_client_server_memory_streams()` remains, but the streams it yields no longer expose anyio's `send_nowait`, `receive_nowait`, or `statistics()`.

### Deprecated v1 calls now warn (breaks warnings-as-errors test runs)

The APIs the 2026-07-28 spec deprecates — the `Context` logging helpers (`await ctx.info(...)` and friends), the sampling and roots calls, the ported `on_set_logging_level=`-style handlers, and the rest listed in [Deprecated features](deprecated.md) — keep working but now emit `MCPDeprecationWarning`, a `UserWarning` subclass exported from `mcp`. A test suite configured with `filterwarnings = ["error"]` therefore fails on unchanged code, and strict type checkers flag the calls (`reportDeprecated`). Update the calls, or add a `default` filter for the category after the `error` entry:

```toml
[tool.pytest.ini_options]
filterwarnings = [
    "error",
    "default::mcp.MCPDeprecationWarning",
]
```

## Behavior changes on v2's default connection

v2's `Client` (including the in-process `Client(server)` that replaces v1's test helper) negotiates the 2026-07-28 protocol by default, so the v1 patterns below change behavior even though the server code is untouched. `Client(..., mode="legacy")` reproduces v1's `initialize` handshake and restores each of them; connections negotiated at 2025-11-25 or earlier (a `ClientSession` you `initialize()` yourself, any 2025-era peer) are unaffected.

### Server-initiated sampling, elicitation, and roots raise `NoBackChannelError`

A handler that reaches back to the client mid-request — `ctx.elicit()`, `ctx.elicit_url()`, `ctx.session.create_message()`, `ctx.session.list_roots()`, or any other `ServerSession` request helper — raises `NoBackChannelError` where the connection has no server-to-client channel: every 2026-07-28 connection (the protocol has no server-initiated requests), a legacy session against a `stateless_http=True` server, and the request-scoped channel of a legacy session against a `json_response=True` server. In the last two cases the v1 call hung until the client's read timeout; v2 fails fast. So an unchanged v1 sampling or elicitation tool fails on its first `Client(server)` test, and `sampling_callback=` / `elicitation_callback=` change nothing — no request ever reaches the client.

`NoBackChannelError` (`mcp.shared.exceptions`) subclasses `MCPError` with code `-32600` and message `Cannot send '<method>': this transport context has no back-channel for server-initiated requests.`. Raised inside a handler it reaches the client as a JSON-RPC error, not `CallToolResult(is_error=True)` (see [`MCPError` raised from an `@mcp.tool()` handler now surfaces as a JSON-RPC error](#mcperror-raised-from-an-mcptool-handler-now-surfaces-as-a-json-rpc-error)). Notification helpers never raise it: undeliverable notifications are dropped instead (see the next two sections). `UrlElicitationRequiredError` is unaffected; it is an error response, not a request.

Two ways to migrate:

- **Keep the push behavior for now** by connecting at a pre-2026 version: `Client(server, mode="legacy", sampling_callback=..., elicitation_callback=..., list_roots_callback=...)`; a lowlevel `ClientSession` you `initialize()` yourself already negotiates a 2025-era version. Sampling and roots stay deprecated on this path ([Deprecated features](deprecated.md)).
- **Port to the era-portable form**: a `Resolve(...)`-backed parameter whose resolver returns `Elicit`, `Sample`, or `ListRoots` makes the server return the question instead of pushing it — the SDK elicits directly on a legacy connection and drives the `InputRequiredResult` multi-round trip at 2026-07-28, with one handler body for both eras; see [Dependencies](handlers/dependencies.md), [Multi-round-trip requests](handlers/multi-round-trip.md), and [Serving legacy clients](run/legacy-clients.md).

**Before (v1):**

```python
@mcp.tool()
async def book_table(date: str, ctx: Context) -> str:
    result = await ctx.elicit(f"Book a table for {date}?", schema=Confirmation)
    if result.action == "accept" and result.data.confirm:
        return f"Booked for {date}."
    return "No booking made."
```

**After (v2), era-portable:**

```python
from typing import Annotated

from mcp.server.mcpserver import Elicit, Resolve


async def ask_to_confirm(date: str) -> Elicit[Confirmation]:
    return Elicit(f"Book a table for {date}?", Confirmation)


@mcp.tool()
async def book_table(date: str, answer: Annotated[Confirmation, Resolve(ask_to_confirm)]) -> str:
    if answer.confirm:
        return f"Booked for {date}."
    return "No booking made."
```

The client keeps the same `elicitation_callback`; it now answers the returned question.

### Log messages are delivered only to requests that opt in

A migrated test whose `logging_callback` received every `notifications/message` in v1 now receives none: on a 2026-07-28 connection protocol logging is a per-request opt-in, so `ctx.info(...)` / `ctx.log(...)` on `MCPServer`'s `Context` and `ctx.session.send_log_message(...)` are dropped (debug-logged) unless the request's `_meta` carries `io.modelcontextprotocol/logLevel` at or above the message level. `logging/setLevel` no longer exists either: `client.set_logging_level(...)` raises `MCPError` (`-32601`, method not found) even when the server registered a handler. Opt in with `log_level=` on `Client` (a per-call `meta=` entry overrides it), or pin `Client(server, mode="legacy", ...)` to keep v1's push delivery. See [Client callbacks](client/callbacks.md#the-notification-callbacks).

```python
from mcp import Client
from mcp.types import LOG_LEVEL_META_KEY

async with Client(server, logging_callback=on_log, log_level="info") as client:
    await client.call_tool("chatty", {})  # on_log receives info and above
    await client.call_tool("chatty", {}, meta={LOG_LEVEL_META_KEY: "debug"})  # this call: debug and above
```

### Change notifications travel only on `subscriptions/listen` streams

The v1 helpers `ctx.session.send_tool_list_changed()`, `send_prompt_list_changed()`, `send_resource_list_changed()`, and `send_resource_updated(uri)` are dropped with a debug log on a 2026-07-28 connection: there the four change notifications reach a client only through a `subscriptions/listen` stream it opened. Their 2026 counterparts are `await ctx.notify_tools_changed()` / `notify_prompts_changed()` / `notify_resources_changed()` / `notify_resource_updated(uri)` on `MCPServer`'s `Context`, which reach `subscriptions/listen` streams only ([Subscriptions](handlers/subscriptions.md)); neither call reaches the other era's clients, so to notify everyone call both ([Serving legacy clients](run/legacy-clients.md#where-your-code-actually-forks)).

**Before (v1):**

```python
from mcp.server.fastmcp import Context, FastMCP

mcp = FastMCP("Dynamic Tools")


@mcp.tool()
async def register_plugin(name: str, ctx: Context) -> str:
    # ... register the plugin's tools ...
    await ctx.session.send_tool_list_changed()
    return f"Plugin '{name}' registered"
```

**After (v2):**

```python
from mcp.server import MCPServer
from mcp.server.mcpserver import Context

mcp = MCPServer("Dynamic Tools")


@mcp.tool()
async def register_plugin(name: str, ctx: Context) -> str:
    # ... register the plugin's tools ...
    await ctx.notify_tools_changed()  # 2026-07-28 clients (subscriptions/listen)
    await ctx.session.send_tool_list_changed()  # legacy (<= 2025-11-25) clients
    return f"Plugin '{name}' registered"
```

On a low-level `Server`, publish to your own `SubscriptionBus` (`await bus.publish(ToolsListChanged())` from `mcp.server.subscriptions`) served by `ListenHandler(bus)` on `on_subscriptions_listen=`; see [the low-level composition](handlers/subscriptions.md#the-low-level-composition).

## Need Help?

If you encounter issues during migration:

1. Check the [API Reference](api/mcp/index.md) for updated method signatures
2. Review the [examples](https://github.com/modelcontextprotocol/python-sdk/tree/main/examples) for updated usage patterns
3. Open an issue on [GitHub](https://github.com/modelcontextprotocol/python-sdk/issues) if you find a bug or need further assistance
