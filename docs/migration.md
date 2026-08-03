# Migration Guide: v1 to v2

This guide covers the breaking changes introduced in v2 of the MCP Python SDK and how to update your code.

Version 2 of the MCP Python SDK introduces several breaking changes to improve the API, align with the MCP specification, and provide better type safety.

!!! note "Not ready to migrate yet?"
    The v1.x maintenance line keeps receiving critical bug fixes and security patches, and its
    documentation is at [/v1/](https://py.sdk.modelcontextprotocol.io/v1/). If your package depends
    on `mcp`, keep a `<2` upper bound until you've migrated.

## Find your changes

Every section heading below names the API it affects, so searching this page for the symbol your code uses is the fastest route to the change that broke it. The guide lists changes only: an SDK API not mentioned here behaves as it did in v1, and the "what did not change" summaries — [`MCPServer`](#what-is-unchanged-on-mcpserver), [lowlevel `Server`](#lowlevel-server-what-did-not-change), and [auth](#unchanged-auth-surfaces) — spell out the surfaces most migrators stop to check.

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
| httpx | `>=0.27.1,<1.0.0` | removed | see [`httpx` and `httpx-sse` replaced by `httpx2`](#httpx-and-httpx-sse-replaced-by-httpx2) |
| httpx-sse | `>=0.4` | removed | see [`httpx` and `httpx-sse` replaced by `httpx2`](#httpx-and-httpx-sse-replaced-by-httpx2) |
| httpx2 | not a dependency | `>=2.5.0` | new required dependency |
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

### `httpx` and `httpx-sse` replaced by `httpx2`

The SDK now depends on [`httpx2`](https://pypi.org/project/httpx2/) instead of
`httpx` and `httpx-sse`. `httpx2` is the next-generation HTTP client (a fork of
`httpx`) with server-sent events support built in, so the separate `httpx-sse`
dependency is gone.

The swap changes types, not parameter lists: `streamable_http_client` and `sse_client`
keep their keyword arguments (covered, with the removed `streamablehttp_client` alias and the
`get_session_id` callback, under [Transports](#transports)), and only the objects they take
become `httpx2` types — the pre-built `http_client` you hand `streamable_http_client`,
`sse_client`'s `auth=` (an `httpx2.Auth`, the base class `OAuthClientProvider` now uses), and
the client a custom `httpx_client_factory` returns. Import from `httpx2` when building any of
them:

**Before (v1):**

```python
import httpx

http_client = httpx.AsyncClient(follow_redirects=True)
```

**After (v2):**

```python
import httpx2

http_client = httpx2.AsyncClient(follow_redirects=True)
```

`httpx2` is API-compatible with `httpx`, so usually only the import name
changes. To consume SSE directly, use `httpx2.EventSource` (or
`AsyncClient.sse()`) instead of the `httpx-sse` helpers.

mcp no longer installs `httpx` at all. If your own code imports `httpx` and relied on mcp
v1 to pull it in, that import now fails with
`ModuleNotFoundError: No module named 'httpx'` — a traceback that never mentions mcp. Either
add `httpx` to your own dependencies (the two packages install side by side; only objects
handed to the SDK via `http_client=` or `auth=` have to be `httpx2` types) or port those
calls to `httpx2`, whose `Client` and `AsyncClient` are drop-in replacements.

Exception handlers need the same rename: the SDK now raises `httpx2`
exceptions (`httpx2.ConnectError`, `httpx2.HTTPStatusError`, and so on), and
this failure mode is silent. If `httpx` is still installed — your own code or another
package depends on it — an old `except httpx.ConnectError:` block
keeps importing fine and simply never matches again. Audit `except httpx.`
clauses and `isinstance` checks along with the imports, and switch test fixtures in the
same change: `pytest.raises(httpx.ConnectError)`, an `httpx.MockTransport`, or a test-only
`httpx.Auth` subclass all target the wrong types once the code under test moves to `httpx2`.
The same identity split applies to objects: `httpx` and `httpx2` types are not
interchangeable at runtime, so an `httpx.AsyncClient` passed as `http_client` degrades in
subtle ways (server-initiated messages stop arriving) instead of raising immediately.

Retry and error-classification logic keyed to HTTP status codes needs a look too: through
the SDK's client, timeouts and non-2xx responses surface as `MCPError` with JSON-RPC codes,
not `408`s or `httpx.HTTPStatusError` — see the client request timeouts section
(`REQUEST_TIMEOUT`, `-32001`) under [Clients](#clients) and
[Streamable HTTP: non-2xx responses now surface as per-request JSON-RPC errors](#streamable-http-non-2xx-responses-now-surface-as-per-request-json-rpc-errors).

The SDK's own auth providers made the same move: `OAuthClientProvider`,
`ClientCredentialsOAuthProvider`, `PrivateKeyJWTOAuthProvider`, and
`IdentityAssertionOAuthProvider` now subclass `httpx2.Auth` (v1: `httpx.Auth`),
so the client you attach one to must be an `httpx2.AsyncClient`. Unlike the
silent `http_client` degradation, this direction fails loudly at
construction: `httpx.AsyncClient(auth=provider)` raises
`TypeError: Invalid "auth" argument`. See [OAuth clients](client/oauth-clients.md)
for the `httpx2.AsyncClient(auth=...)` wiring.

The client also identifies itself differently: the default User-Agent is now
`python-httpx2/<version>`, and log lines come from the `httpx2` and
`httpcore2.*` loggers, so a `logging.getLogger("httpx")` or
`logging.getLogger("httpcore")` suppression no longer matches anything — target
`logging.getLogger("httpx2")` and `logging.getLogger("httpcore2")` instead.
Telemetry integrations keyed to the `httpx` module (such as OpenTelemetry's
httpx instrumentation) stop seeing the SDK's traffic as well.

TLS verification also changes: `httpx` validated certificates against the
bundled `certifi` CA list, while `httpx2` validates against the operating
system trust store via [`truststore`](https://pypi.org/project/truststore/).
If your environment has no usable system CA store (some minimal containers),
or you relied on certifi's bundle specifically, point the standard
`SSL_CERT_FILE` or `SSL_CERT_DIR` environment variable at a CA bundle
(`httpx2` honors these before falling back to the system store), or pass an
explicit `verify=ssl_context` to your `httpx2.AsyncClient`. Passing a CA
bundle path as `verify="ca.pem"` or using the `cert=` parameter is deprecated
in `httpx2`; build an `ssl.SSLContext` and configure it instead.

### `mcp dev` and `mcp install` pin the spawned environment to your SDK version

Both commands run your server through a fresh `uv run --with ...` environment. In v1 the
`mcp` requirement in that command was unpinned, so the spawned environment resolved to the
newest stable release rather than the version you had installed; while v2 was in
pre-release, `mcp dev server.py` built a v1 environment that could not import a v2 server.
Both commands now pin the requirement to the version you are running
(`mcp==<installed version>`). Source builds and other unpublished versions, which have
nothing on PyPI to pin to, keep the unpinned form.

## Types and wire format

### `mcp.types` moved to the `mcp-types` package

The protocol wire types now live in a standalone distribution, `mcp-types` (import package
`mcp_types`). Its only runtime dependencies are `pydantic` and `typing-extensions`, so code
that just needs to (de)serialize MCP traffic can install it without the full SDK. Its API
reference is at [`mcp_types`](api/mcp_types/index.md).

**If your project depends on `mcp`, nothing changes for you.** `import mcp.types`,
`from mcp.types import ...`, `from mcp import types`, and `import mcp` followed by
`mcp.types.Tool` all keep working: `mcp.types` is a permanent alias that mirrors `mcp_types`
exactly (every name is the same object), and `mcp.types.version` mirrors
`mcp_types.version` the same way. Keep importing through `mcp` — the package you actually
depend on — rather than writing `import mcp_types`, which would reach past your declared
dependency into a transitive one. The old `mcp.shared.version` module was removed; import the
version registry from `mcp.types.version` instead. The top-level `from mcp import Tool`
re-exports are unchanged too.

**Import `mcp_types` directly only in a project that depends on `mcp-types` without the
SDK.** That is the point of the split: tooling and lightweight clients can depend on the
protocol schema without pulling in `httpx2`, `starlette`, `uvicorn`, and the rest of the
server/transport stack.

Names that no longer exist (listed under
[Removed type aliases and classes](#removed-type-aliases-and-classes)) fail on import or
attribute access with an ordinary `ImportError` / `AttributeError`; the table below names each
replacement.

The supported import surface is the package plus its `jsonrpc`, `methods`, and `version`
submodules, and each has both spellings: `mcp.types` / `mcp_types`, `mcp.types.jsonrpc` /
`mcp_types.jsonrpc`, `mcp.types.methods` / `mcp_types.methods`, and `mcp.types.version` /
`mcp_types.version` (each `mcp.types` module mirrors its `mcp_types` counterpart, name for
name, the same objects). Underscore-prefixed submodules (`mcp_types._types`, and the generated
per-protocol-version packages `mcp_types._v2025_11_25` / `mcp_types._v2026_07_28`) are internal
validators with unstable class names; don't import from them, under either spelling.

**Before (v1):**

```python
from mcp.types import Tool, Resource
from mcp.shared.version import LATEST_PROTOCOL_VERSION
```

**After (v2), depending on `mcp`:**

```python
from mcp.types import Tool, Resource  # unchanged
from mcp.types.version import LATEST_PROTOCOL_VERSION
```

**After (v2), depending only on `mcp-types` (no SDK):**

```python
from mcp_types import Tool, Resource
from mcp_types.version import LATEST_PROTOCOL_VERSION
```

### Removed type aliases and classes

The following type aliases and classes have been removed from the protocol types (`mcp.types` / `mcp_types`):

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
from mcp.types import ContentBlock, ResourceTemplateReference
# Use `str` instead of `Cursor` for pagination cursors
```

### Field names changed from camelCase to snake_case

All Pydantic model fields in the protocol types now use snake_case names for Python attribute access. The JSON wire format is unchanged — traffic the SDK sends still uses camelCase via Pydantic aliases, but your own `model_dump()` calls now need `by_alias=True` to produce it.

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
from mcp.types import CallToolRequestParams

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

# Params are constructed as before; only the outer wrapper is gone
await session.send_notification(
    CancelledNotification(params=CancelledNotificationParams(request_id=request_id, reason="timeout"))
)
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

These are ordinary `X | Y` unions of the concrete pydantic classes, so `isinstance(msg, ServerNotification)`, `isinstance(msg, LoggingMessageNotification)`, and `match`/`case` on the member classes keep working (unlike `ElicitationResult`, which became a `TypeAliasType` — see [`isinstance()` checks against `ElicitationResult` raise `TypeError`](#isinstance-checks-against-elicitationresult-raise-typeerror)).

Values the SDK hands you are the member instances themselves, so delete `.root` accesses. A `message_handler`, for example, now receives the notification directly (v1 code fails with `AttributeError: 'LoggingMessageNotification' object has no attribute 'root'`):

```python
# Before (v1)
if isinstance(message, ServerNotification):
    if isinstance(message.root, LoggingMessageNotification):
        print(message.root.params.data)

# After (v2)
if isinstance(message, LoggingMessageNotification):
    print(message.params.data)
```

Custom transports and `EventStore` implementations follow the same rule: `mcp.shared.message.SessionMessage` takes the member directly (`SessionMessage(JSONRPCNotification(...))`, not `SessionMessage(JSONRPCMessage(JSONRPCNotification(...)))`), and raw JSON parses with `jsonrpc_message_adapter.validate_json(raw)` instead of `JSONRPCMessage.model_validate_json(raw)`.

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

`SUPPORTED_PROTOCOL_VERSIONS` is deprecated — it's now the union of `HANDSHAKE_PROTOCOL_VERSIONS` (initialize-handshake versions) and `MODERN_PROTOCOL_VERSIONS` (per-request-envelope versions). If you were using it to mean "versions the initialize handshake accepts", switch to `HANDSHAKE_PROTOCOL_VERSIONS`. Named scalars derived from these tuples are now exported alongside them — `LATEST_HANDSHAKE_VERSION`, `LATEST_MODERN_VERSION`, `OLDEST_SUPPORTED_VERSION` — so prefer those over indexing the tuples directly. All of these live in `mcp.types.version` (an alias of `mcp_types.version`; previously `mcp.shared.version`): `from mcp.types.version import HANDSHAKE_PROTOCOL_VERSIONS`.

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
from mcp.types import INVALID_REQUEST

raise MCPError(INVALID_REQUEST, "bad input")
# or, if you already have an ErrorData:
raise MCPError.from_error_data(error_data)
```

### `JSONRPCError.id` is now `RequestId | None`

In v1 `JSONRPCError.id` was typed `str | int`, so an error response with `"id": null` failed validation even though JSON-RPC 2.0 allows it (the id is null when the receiver could not determine the request id, e.g. a parse error). In v2 the field is `RequestId | None`: still required, but `None` is accepted, and `jsonrpc_message_adapter` parses a null-id error into a `JSONRPCError`.

**Before (v1):**

```python
from mcp.types import JSONRPCMessage

# Raised ValidationError: id could not be None
JSONRPCMessage.model_validate(
    {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
)
```

**After (v2):**

```python
from mcp.types import PARSE_ERROR, ErrorData, JSONRPCError, jsonrpc_message_adapter

message = jsonrpc_message_adapter.validate_python(
    {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
)
assert isinstance(message, JSONRPCError) and message.id is None

# Constructing one: `id` is required but nullable
JSONRPCError(jsonrpc="2.0", id=None, error=ErrorData(code=PARSE_ERROR, message="Parse error"))
```

Delete any shim that accepted or synthesized null-id error responses. Code that assumed `error.id` was always a `str | int` must now handle `None`, and tests that pinned v1's rejection of `"id": null` now fail because validation succeeds.

## MCPServer (formerly FastMCP)

### `FastMCP` renamed to `MCPServer`

The `FastMCP` class has been renamed to `MCPServer` to better reflect its role as the main server class in the SDK. Beyond the name and import path, the changes to the class are covered in the sections that follow, and [What is unchanged on `MCPServer`](#what-is-unchanged-on-mcpserver) lists the everyday surface that carries over as-is.

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
- `Icon` — from `mcp.server.mcpserver` or `mcp.types` (not a top-level `mcp` export); its `mimeType` field is now `mime_type` per the [snake_case renames](#field-names-changed-from-camelcase-to-snake_case), though the `mimeType=` kwarg still constructs
- `Message`, `UserMessage`, `AssistantMessage` — from `mcp.server.mcpserver.prompts.base`
- `ToolError`, `ResourceError` — from `mcp.server.mcpserver.exceptions`
- `MCPServerError` (renamed from `FastMCPError`) — from `mcp.server.mcpserver.exceptions`

### What is unchanged on `MCPServer`

Beyond the changes covered in this section, the everyday `FastMCP` surface carries over to `MCPServer` as-is:

- **Decorators.** `@mcp.tool()`, `@mcp.resource()`, `@mcp.prompt()`, and `@mcp.completion()` take the same arguments and handler signatures as v1. The lowlevel [`on_completion` reshape](#lowlevel-server-decorator-based-handlers-replaced-with-constructor-on_-params) applies only to the lowlevel `Server`; a high-level `@mcp.completion()` handler is still called as `(ref, argument, context)`.
- **Tool return handling.** A returned `CallToolResult` (including an `Annotated[CallToolResult, YourModel]` output schema, and `_meta`) is passed through, `Image` and `Audio` convert to content blocks as before, ready-made content blocks are kept as-is, and dict, list, scalar, and model returns are wrapped into `content` and `structured_content` by the same rules.
- **Listing and registration methods.** `list_tools()`, `list_resources()`, `list_resource_templates()`, and `list_prompts()` return the same lists and are still what the protocol handlers call, so subclass overrides still take effect. `add_tool()`, `add_resource()`, and `add_prompt()` are unchanged.
- **Helpers.** `Image.to_image_content()`, `Audio.to_audio_content()`, and the prompt `Message`, `UserMessage`, and `AssistantMessage` classes.
- **Lifespan.** The `lifespan=` constructor argument and `ctx.request_context.lifespan_context` work as before, and the class is still generic over the lifespan result: `FastMCP[MyState]` becomes `MCPServer[MyState]`. (`Context`'s own type parameters did change; see [`RequestContext` type parameters simplified](#requestcontext-type-parameters-simplified).)
- **Tool internals.** `Tool`, `Tool.from_function()`, `FuncMetadata`, `ArgModelBase`, and `func_metadata()` keep their v1 shapes; the one change is the now-required `context` argument to `Tool.run()`, described [below](#mcpservercall_tool-read_resource-get_prompt-now-accept-a-context-parameter).
- **Auxiliary import paths.** `TransportSecuritySettings` (`mcp.server.transport_security`) and `AcceptedElicitation`/`DeclinedElicitation`/`CancelledElicitation` (`mcp.server.elicitation`) have not moved; the server auth surface is inventoried under [Unchanged auth surfaces](#unchanged-auth-surfaces).

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

### Unversioned servers report an empty version

In v1, a server constructed without a `version` reported the installed `mcp`
package's version as its own in the `initialize` result's `serverInfo`. In v2
it reports an empty string instead: the SDK's version is not your server's
version. Pass `version="..."` to `Server(...)` or `MCPServer(...)` to identify
your server properly. The field is display-only; nothing breaks either way.

### `mount_path` parameter removed from MCPServer

The `mount_path` parameter has been removed from `MCPServer.__init__()`, `MCPServer.run()`, `MCPServer.run_sse_async()`, and `MCPServer.sse_app()`. It was also removed from the `Settings` class.

This parameter was redundant because the SSE transport already handles sub-path mounting via ASGI's standard `root_path` mechanism. When using Starlette's `Mount("/path", app=mcp.sse_app())`, Starlette automatically sets `root_path` in the ASGI scope, and the `SseServerTransport` uses this to construct the correct message endpoint path.

### Transport-specific parameters moved from MCPServer constructor to run()/app methods

Transport-specific parameters have been moved off the `MCPServer` constructor and onto `run()`, `sse_app()`, and `streamable_http_app()`, so transport configuration is passed when starting or building the server. The rest of the constructor is unchanged: identity (`name`, `instructions`, `website_url`, `icons`, plus the newly added positional `title`, `description`, and `version` covered [above](#mcpserver-constructor-title-description-and-version-added-to-the-positional-parameters)), authentication (`auth`, `token_verifier`, `auth_server_provider`), `lifespan`, `dependencies`, `tools`, `debug`, `log_level`, and the `warn_on_duplicate_*` flags; the new keyword-only parameters (`resources`, `extensions`, `resource_security`, `request_state_security`, `cache_hints`, `subscriptions`, `middleware`) are additive.

**Parameters moved:**

- `host`, `port` - HTTP server binding, on `run()` only. The app factories have no `port` (`streamable_http_app(port=...)` raises `TypeError`; a mounted app binds wherever the outer ASGI server does) but do take `host` (default `"127.0.0.1"`), used only to decide whether DNS rebinding protection auto-enables (see the note below)
- `sse_path`, `message_path` - SSE transport paths, on `run(transport="sse", ...)` and `sse_app()`
- `streamable_http_path` - StreamableHTTP endpoint path, on `run(transport="streamable-http", ...)` and `streamable_http_app()`
- `json_response`, `stateless_http` - StreamableHTTP behavior, same two places; each also removes a server-to-client channel, see [Server-initiated sampling, elicitation, and roots raise `NoBackChannelError`](#server-initiated-sampling-elicitation-and-roots-raise-nobackchannelerror)
- `max_request_body_size` - StreamableHTTP request-body limit, same two places
- `event_store`, `retry_interval` - StreamableHTTP event handling, same two places
- `transport_security` - DNS rebinding protection, on `run()` for both HTTP transports and on both app methods

`run()` is `@overload`ed per transport, so type checkers validate the keywords each transport accepts (`transport="stdio"` takes none); at runtime the HTTP transports raise `TypeError` on an unrecognised keyword when they start.

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
mcp.run(transport="streamable-http", host="0.0.0.0", port=9000, json_response=True, stateless_http=True)

# Or for SSE
mcp = MCPServer("Server")
mcp.run(transport="sse", host="0.0.0.0", port=9000, sse_path="/events")
```

**For mounted apps:**

When mounting in a Starlette app, pass transport params to `streamable_http_app()`. As in v1, the host app's lifespan must enter `mcp.session_manager.run()` — a mounted sub-app's own lifespan never runs, so nothing else starts the session manager:

```python
import contextlib

# Before (v1)
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("App", json_response=True)

# After (v2)
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("App")


# Unchanged from v1: the host app's lifespan runs the session manager
@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with mcp.session_manager.run():
        yield


# Before (v1)
app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app())], lifespan=lifespan)

# After (v2)
app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app(json_response=True))], lifespan=lifespan)
```

Without `lifespan=lifespan` the app starts but every request to the mounted path fails with `RuntimeError: Task group is not initialized. Make sure to use run().` — `mcp.session_manager` is the same public property v1's `FastMCP.session_manager` was, and it still exists only after `streamable_http_app()` has been called, so build the routes at module level and touch the manager only inside the lifespan. See [Add to an existing app](run/asgi.md) for the full pattern, including several servers in one app.

v2 has no settings object that carries transport configuration, so if the module that configures the server is not the one that builds the ASGI app, carry the keywords yourself, e.g. `build_app = functools.partial(mcp.streamable_http_app, json_response=True, stateless_http=True)` next to the server definition and `Mount("/", app=build_app())` wherever it is mounted.

**Note:** DNS rebinding protection is automatically enabled when `host` is `127.0.0.1`, `localhost`, or `::1` and no `transport_security` is passed. This now happens in `sse_app()` and `streamable_http_app()` instead of the constructor, and because those default to `host="127.0.0.1"`, a mounted app has protection on until you configure it. The auto-allowlist entries are `host:port` patterns (`127.0.0.1:*`, `localhost:*`, `[::1]:*`), so a request whose `Host` header carries no port (some in-process test clients send a bare `Host: localhost`) is rejected with `421 Invalid Host header`. To serve a real hostname, pass `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` (from `mcp.server.transport_security`); [Deploy & scale](run/deploy.md) and [Troubleshooting](troubleshooting.md) cover the allowlist and the `421` in detail.

`Settings` (what `mcp.settings` holds) now has only the constructor-owned fields: `debug`, `log_level`, the `warn_on_duplicate_*` flags, `dependencies`, `lifespan`, and `auth`. If you were mutating transport values via `mcp.settings` after construction (e.g. `mcp.settings.port = 9000`), pass them to `run()` / `sse_app()` / `streamable_http_app()` instead: assigning a removed field now raises `ValueError: "Settings" object has no field "port"`. `settings.lifespan` is read once, at construction, so reassigning it afterwards has no effect. Once `streamable_http_app()` has been called, the values it was built with live on the runtime objects (e.g. `mcp.session_manager.stateless`, `mcp.session_manager.json_response`).

### `MCP_*` environment variables and `.env` files are no longer read

The `Settings` docstring advertised configuration via `MCP_*` environment variables and a `.env` file (e.g. `MCP_DEBUG=true`), but constructor arguments have always taken precedence, so those environment variables never took effect. `Settings` is now a plain Pydantic model rather than a `pydantic-settings` `BaseSettings`, and `pydantic-settings` is no longer a dependency of the SDK.

If you want environment-driven configuration, read the environment yourself and pass the values to the constructor:

```python
import os

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("Demo", debug=os.environ.get("MCP_DEBUG") == "true")
```

If your own code uses `pydantic-settings`, add it to your project's dependencies directly.

### Streamable HTTP request bodies are limited to 4 MiB

V2 applies a 4 MiB default limit to Streamable HTTP POST bodies and returns HTTP 413 before parsing
the JSON or creating a session when that limit is exceeded.

Most servers need no migration. If your application intentionally accepts larger MCP messages,
set an explicit byte limit on `run()` or `streamable_http_app()`:

```python
mcp.run(transport="streamable-http", max_request_body_size=8 * 1024 * 1024)
```

The limit must be positive and applies to both legacy session-based requests and V2's modern
single-exchange requests. Keep the smallest value your application actually needs.

### Streamable HTTP: lifespan now entered once at manager startup

When serving streamable HTTP (stateful or `stateless_http=True`), the server's `lifespan` context manager is now entered once when `StreamableHTTPSessionManager.run()` starts, and the resulting state is shared across all sessions and requests. Previously each session (stateful) or each request (stateless) entered and exited `lifespan` independently.

Lifespans that set up process-wide state (connection pools, caches, background tasks) are unaffected — they now run once instead of per session/request. If your lifespan was acquiring per-connection resources, move that acquisition into the handler body; per-connection cleanup belongs on the connection's `exit_stack` (a public way to reach it from high-level `@mcp.tool()` handlers is planned).

### Streamable HTTP: session manager, `EventStore`, and stateless mode unchanged

Beyond the constructor parameters that moved to `run()`/`streamable_http_app()` and the lifespan change above, the server-side Streamable HTTP machinery is as in v1:

- `mcp.server.streamable_http` still exports the `EventStore` ABC (`store_event()`, `replay_events_after()`), `EventMessage`, `EventCallback`, `EventId`, and `StreamId` with unchanged signatures; a custom `EventStore` keeps importing `JSONRPCMessage` from `mcp.types`, unchanged.
- `StreamableHTTPSessionManager` keeps its constructor and its `run()` / `handle_request()` methods (see [Lowlevel `Server`: what did not change](#lowlevel-server-what-did-not-change)); its `stateless=` parameter is unrelated to the removed [`Server.run(stateless=)` flag](#serverrun-no-longer-takes-a-stateless-flag).
- `mcp.session_manager` still returns the manager once `streamable_http_app()` has been called, with the same `stateless`, `json_response`, `event_store`, and `retry_interval` attributes.
- `stateless_http=True` still serves each request with a fresh transport, no `Mcp-Session-Id`, and no state carried between requests; `ctx.close_sse_stream()` and `ctx.close_standalone_sse_stream()` are still available on the handler `Context`.

Only private attributes moved: `mcp._mcp_server` is now `mcp._lowlevel_server` (see [Registering lowlevel handlers from `MCPServer`](#registering-lowlevel-handlers-from-mcpserver)), and `_session_manager` now lives on that lowlevel `Server`. Prefer the public `mcp.session_manager` property to either.

### `MCPServer.get_context()` removed

`MCPServer.get_context()` has been removed. Context is now injected by the framework and passed explicitly — there is no ambient ContextVar to read from.

**If you were calling `get_context()` from inside a tool/resource/prompt:** use the `ctx: Context` parameter injection instead.

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
live back-channel too; a pre-`2026-07-28` session with no back-channel
(stateless HTTP, or streamable HTTP with `json_response=True`) keeps failing
with its no-back-channel error. At `2026-07-28` a resolver never uses a
back-channel — it answers with an `InputRequiredResult` — so the `-32021`
check applies there unconditionally. To migrate, declare the capability: the SDK client
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

The client sees this change too. `Client.call_tool()` and
`ClientSession.call_tool()` raise on a JSON-RPC error response, so a tool that
rejects with `MCPError` now raises `MCPError` on the calling side (`code`,
`message`, and `data` intact) instead of returning a `CallToolResult` with
`isError=True` and the message in `content`:

```python
# Before (v1)
result = await session.call_tool("book_flight", {"date": "yesterday"})
if result.isError:
    ...  # error text is in result.content

# After (v2)
try:
    result = await client.call_tool("book_flight", {"date": "yesterday"})
except MCPError as e:
    ...  # e.code, e.message, e.data
```

### Resource not found returns `-32602` and resource lookups raise typed exceptions (SEP-2164)

Reading a missing resource now returns JSON-RPC error code `-32602` (invalid params) with the requested URI in `error.data` (`{"uri": ...}`), per [SEP-2164](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2164). Previously the server returned code `0` with no `data`. Clients can now reliably distinguish not-found from other errors; a template handler that raises `ResourceNotFoundError` (from `mcp.server.mcpserver.exceptions`) produces this same response.

The underlying lookups now raise typed exceptions instead of `ValueError`. `ResourceManager.get_resource()` raises `ResourceNotFoundError` when no resource or template matches the URI, and `ResourceTemplate.create_resource()` raises `ResourceError` when the template function fails. Neither subclasses `ValueError`, so callers catching `ValueError` should switch to `ResourceNotFoundError` / `ResourceError` (both importable from `mcp.server.mcpserver.exceptions`; `ResourceNotFoundError` subclasses `ResourceError`).

### `Resource` classes reject unknown keyword arguments

The `Resource` base class now sets `extra="forbid"`, so every resource class — `TextResource`, `BinaryResource`, `FunctionResource`, `FileResource`, `HttpResource`, `DirectoryResource`, and your own subclasses — raises `ValidationError` on an unrecognised keyword argument instead of silently dropping it. Previously a typo'd or since-removed parameter (such as `FileResource(is_binary=...)`, below) was accepted and ignored. Remove any stray keyword arguments; if a subclass needs to accept arbitrary extras, set its own `model_config = ConfigDict(extra="allow")`.

### `FileResource.is_binary` replaced by `encoding`

`FileResource` used to take `is_binary: bool` and guess its default from `mime_type` (`text/*` → text, anything else → bytes). Two problems fell out of that: `is_binary=False` could not actually be set — `False` doubled as the "not given" sentinel, so `mime_type="application/json"` always came back as a base64 blob — and text reads used `Path.read_text()` with no encoding, i.e. the platform locale (cp1252 on Windows).

The field is now `encoding: str | None`. A string means "decode with this encoding and serve as text"; `None` means "read bytes and serve as a blob". When omitted it defaults to the `charset` declared in `mime_type` if there is one, otherwise `"utf-8-sig"` for textual mime types (`text/*`, `application/json`, `application/xml`, and any `+json`/`+xml` suffix) and `None` for everything else, so JSON and XML files are now served as text without any configuration. `utf-8-sig` is plain UTF-8 that also drops a byte-order mark if the file has one; a declared `charset=` is used as-is.

Passing the removed `is_binary=` argument now raises a `ValidationError` at construction (see the section above) rather than being silently ignored. A misspelled `encoding` also fails at construction rather than on the first read.

Two edge cases to check. A non-UTF-8 file with a *newly* textual mime type (say a UTF-16 `application/xml`) previously shipped byte-exact as a blob and now fails to decode. And an existing `text/*` file that was only readable through your platform's locale encoding (v1 decoded these with the locale, not UTF-8) now fails too. In both cases set `encoding` to the file's real encoding, or `encoding=None` to serve the bytes as a blob.

**Before (v1):**

```python
FileResource(uri="file:///logo.png", path=logo, mime_type="image/png", is_binary=True)
FileResource(uri="file:///notes.txt", path=notes)  # text, decoded with the locale encoding
```

**After (v2):**

```python
FileResource(uri="file:///logo.png", path=logo, mime_type="image/png")  # bytes, from mime_type
FileResource(uri="file:///notes.txt", path=notes)  # text, decoded as UTF-8 (BOM tolerated)
FileResource(uri="file:///data.json", path=data, mime_type="application/json")  # now text, not a blob
```

Pass `encoding=None` to force a blob, or `encoding="latin-1"` (etc.) to decode a text file that isn't UTF-8.

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
could never be read). This now raises `ValueError` at decoration time
— resource `Context` injection is only wired up for templates. What to
do instead depends on why the handler wanted the context. For lifespan
or application state (what you would read from
`ctx.request_context.lifespan_context`), a static handler is an
ordinary function, so read that state from a module-level object (or
closure) that your `lifespan` populates. For anything on the request
itself (logging, progress, the session), keep the `Context` parameter
and add a template variable so the handler registers as a template; an
optional query variable is enough, and a plain `notes://recent` read
still matches with the default filled in:

```python
@mcp.resource("notes://recent{?limit}")
async def recent_notes(ctx: Context, limit: int = 10) -> str: ...
```

Such a resource is advertised by `resources/templates/list` rather than
`resources/list`.

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

These helpers are themselves deprecated by [SEP-2577](#roots-sampling-and-logging-methods-deprecated-sep-2577) and emit `mcp.MCPDeprecationWarning` on every call, so treat the rename as a keep-it-working fix rather than a migration target: nothing in-protocol replaces pushing log messages to the client, so log with the standard `logging` module instead (see [Logging](handlers/logging.md)) and use `ctx.report_progress()` for progress the client should see.

### `Context.client_id` removed

`Context.client_id` has been removed. It never returned an authenticated client identity: it echoed a non-standard `client_id` key from the request's `_meta`, which nothing in the SDK or the MCP spec populates, so it was `None` unless a caller injected `meta={"client_id": ...}` by hand. The name also collided with the OAuth `client_id`, which is what callers usually mean by "the client".

If you were reading a custom `_meta` key, read it from the meta dict directly. If you want the authenticated OAuth client, use the access token:

```python
# Before (v1)
client_id = ctx.client_id

# After (v2) — the raw _meta key, if you were setting it yourself
meta = ctx.request_context.meta
client_id = meta.get("client_id") if meta else None

# After (v2) — the authenticated OAuth client (usually what you want)
from mcp.server.auth.middleware.auth_context import get_access_token

token = get_access_token()
client_id = token.client_id if token else None
```

### `ProgressContext` and `progress()` context manager removed

The `mcp.shared.progress` module (`ProgressContext`, `Progress`, and the `progress()` context manager) has been removed. This module had no real-world adoption — all users send progress notifications via `Context.report_progress()` or `session.send_progress_notification()` directly.

The replacement is `Context.report_progress(progress, total=None, message=None)` in an `MCPServer` handler, or `ctx.session.report_progress(progress, total, message)` from a lowlevel `Server` handler. Two differences from `ProgressContext.progress(amount, message)`:

- **`report_progress` takes the absolute current value, not a delta.** `ProgressContext.progress(amount)` accumulated into a running total, so calling `p.progress(10)` twice reported `20`. Passing the same deltas to `report_progress` reports `10` twice — progress that jitters instead of increasing, with no error. Keep the running total yourself.
- `progress()` raised `ValueError` when the request carried no progress token; `report_progress` is a no-op when the caller did not request progress. The optional `message=` argument is unchanged.

**Before (v1):**

```python
from mcp.shared.progress import progress

with progress(ctx, total=100) as p:
    await p.progress(25, message="step 1")  # running total: 25
    await p.progress(25)                    # running total: 50
```

**After — use `Context.report_progress()` (recommended):**

```python
@mcp.tool()
async def my_tool(x: int, ctx: Context) -> str:
    await ctx.report_progress(25, 100, message="step 1")
    await ctx.report_progress(50, 100)  # absolute value, not a delta
    return "done"
```

**After — lowlevel `Server`:**

```python
await ctx.session.report_progress(50, 100, message="halfway")
```

`ctx.session.report_progress()` also works on the in-process `Client(server)` path (see [Testing utilities](#testing-utilities)); `ctx.session.send_progress_notification(progress_token, progress, total, message)` remains for code that reads `ctx.meta["progress_token"]` itself, and takes the same absolute-value `progress`.

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

Narrowing on `result.action` (`"accept"` / `"decline"` / `"cancel"`) is unaffected. The `TypeError` is specific to `TypeAliasType` aliases like `ElicitationResult`; the `mcp.types` message unions (`ClientRequest`, `ServerNotification`, `JSONRPCMessage`, ...) are ordinary unions and stay `isinstance`-compatible (see [Replace `RootModel` by union types with `TypeAdapter` validation](#replace-rootmodel-by-union-types-with-typeadapter-validation)).

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
from mcp.types import EmptyResult, SetLevelRequestParams, SubscribeRequestParams


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

### Lowlevel `Server`: what did not change

Handler registration, signatures, and return values changed (the sections below); the serving scaffolding around them keeps its v1 import paths and call shapes:

- `server.run(read_stream, write_stream, initialization_options)`, including `raise_exceptions=` (narrowed, see [transport errors no longer re-raised](#lowlevel-serverrunraise_exceptionstrue-transport-errors-no-longer-re-raised)). Only the `stateless=` flag is gone (see [`Server.run()` no longer takes a `stateless` flag](#serverrun-no-longer-takes-a-stateless-flag)).
- `server.create_initialization_options(notification_options=..., experimental_capabilities=...)`, `server.get_capabilities(...)` (its arguments are now optional), and `NotificationOptions(prompts_changed=, resources_changed=, tools_changed=)`. Both methods gained an optional `extensions=` argument. `create_initialization_options()` is still how you build the `InitializationOptions` passed to `run()`; the only value that differs is `server_version` (see [Unversioned servers report an empty version](#unversioned-servers-report-an-empty-version)).
- `InitializationOptions` (`from mcp.server import InitializationOptions`, also `mcp.server.models`) gained optional `title`/`description` fields; `NotificationOptions` is importable from `mcp.server` and `mcp.server.lowlevel` as before.
- `lifespan=` keeps its contract — an async-context-manager factory that receives the `Server` and whose yielded value handlers read as `ctx.lifespan_context` — but is now keyword-only (see [constructor parameters are now keyword-only](#lowlevel-server-constructor-parameters-are-now-keyword-only)) and, under streamable HTTP, entered once at manager startup (see [Streamable HTTP: lifespan now entered once at manager startup](#streamable-http-lifespan-now-entered-once-at-manager-startup)).
- Server-side transports keep their v1 signatures: `mcp.server.stdio.stdio_server()`, `mcp.server.sse.SseServerTransport(endpoint)` (`connect_sse` / `handle_post_message`), and `mcp.server.streamable_http_manager.StreamableHTTPSessionManager`; the one stdio behavior change is [`stdio_server` keeps the protocol streams on private descriptors](#stdio_server-keeps-the-protocol-streams-on-private-descriptors).
- Import paths: `from mcp.server import Server` (preferred), `from mcp.server.lowlevel import Server`, and `from mcp.server.lowlevel.server import Server` all resolve; only the `request_ctx` contextvar left `mcp.server.lowlevel.server` (see [`request_context` property removed](#lowlevel-server-request_context-property-removed)). `mcp.server.lowlevel.helper_types.ReadResourceContents` still exists (it is `MCPServer.read_resource()`'s return type), but lowlevel `on_read_resource` handlers return `ReadResourceResult` (see [automatic return value wrapping removed](#lowlevel-server-automatic-return-value-wrapping-removed)).

So a v1 `main()` carries over untouched:

```python
async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(notification_options=NotificationOptions(tools_changed=True)),
        )
```

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

All `params` and return types are importable from `mcp.types`.

**Notification handlers:**

```python
from mcp.server import Server, ServerRequestContext
from mcp.types import ProgressNotificationParams


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
from mcp.types import CallToolResult, TextContent


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

**Note:** `Server.middleware` and the `ServerMiddleware` / `CallNext` / `HandlerResult` types in `mcp.server.context` are marked provisional in the source — their signature and semantics may change — so use middleware to observe (log, time, trace) rather than as a foundation. See [Middleware](advanced/middleware.md).

### Lowlevel `Server.run(raise_exceptions=True)`: transport errors no longer re-raised

`raise_exceptions=True` now only governs handler exceptions: an exception raised by an `on_*` handler propagates out of `run()`. The JSON-RPC error response is still written to the client first, regardless of the flag.

Previously it also re-raised exceptions yielded by the transport onto the read stream (e.g. JSON parse errors). Those are now debug-logged and dropped regardless of `raise_exceptions`. If you relied on `run()` exiting on a transport-level parse error, that no longer happens.

### Cancelled requests are no longer answered

In v1, when the peer sent `notifications/cancelled` for an in-flight request, the receiving side interrupted the handler and answered the request anyway with a JSON-RPC error, `{"code": 0, "message": "Request cancelled"}` - and `0` is not a defined JSON-RPC error code. The 2026-07-28 transport specifications (stdio, streamable HTTP) say a server **MUST NOT** send any further messages for a cancelled request; the older cancellation pattern already said it **SHOULD NOT**. The sender is expected to stop waiting once it cancels, so that error response has been removed: a cancelled request now produces no response at all - no result, and no error - even if the handler runs to completion or fails afterwards. This applies to both seats (the server for cancelled client requests, and the client for cancelled server-initiated requests such as sampling or elicitation).

The one deliberate exception is the 2025-era streamable HTTP transport (`StreamableHTTPServerTransport`), whose wire can end a request's stream only with a response for that id (and stores that response so a resuming client's replay terminates too). Under the 2025 rule, a SHOULD NOT, that transport now terminates a cancelled request with a valid `-32800` error (`mcp.server.streamable_http.REQUEST_CANCELLED`, mirroring LSP's `RequestCancelled`) in place of the old `0`. Nothing else answers.

Nothing changes for callers of the built-in client: abandoning a call (cancelling the awaiting task, or a per-request timeout) never waited for that response. If you send `notifications/cancelled` by hand while still awaiting the call, the call now receives nothing on most transports (over 2025-era streamable HTTP it fails with `REQUEST_CANCELLED`); stop awaiting it yourself, or use a per-request timeout.

### `Server.run()` no longer takes a `stateless` flag

The `stateless: bool` parameter on the lowlevel `Server.run()` has been removed. Stateless serving is now a property of how the connection is constructed (the streamable-HTTP manager builds a born-ready `Connection` per request), not a flag the loop driver inspects.

Server-initiated requests that have no channel to travel on — a legacy session against a `stateless_http=True` server, the request-scoped channel of a stateful legacy session against a `json_response=True` server, or any connection negotiated at 2026-07-28 — now raise `NoBackChannelError` instead of stalling as they did in v1 (the transport silently dropped the outbound message), so a stateless-HTTP or JSON-mode `ctx.elicit()` that used to hang now fails fast; see [Server-initiated sampling, elicitation, and roots raise `NoBackChannelError`](#server-initiated-sampling-elicitation-and-roots-raise-nobackchannelerror) for the exception and the migration paths.

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

`ClientRequestContext` (importable from `mcp.client` or `mcp.client.context`) is smaller: a keyword-only dataclass with just `session: ClientSession`, `request_id: RequestId`, and `meta: RequestParamsMeta | None` — no `lifespan_context` or `request` on the client side. Its `request_id` is always a concrete `RequestId`, since the context is only built for the server-initiated `sampling`, `elicitation`, and `roots` requests it is passed to.

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

The parametrized `Context[MyLifespanState]` annotation currently works only on `@mcp.tool()` handlers. On `@mcp.prompt()` and templated `@mcp.resource("scheme://{param}")` handlers, annotate the parameter as bare `Context` for now: these handlers are wrapped in `pydantic.validate_call`, which re-validates the injected `Context` into a fresh `Context[MyLifespanState]` detached from the request, so the first access to `ctx.request_id`, `ctx.session`, or `ctx.request_context` raises `ValueError: Context is not available outside of a request` (the client sees an internal server error, or `Error creating resource from template ...`). Bare `Context` still exposes `ctx.request_context.lifespan_context`; only its static type is lost.

### `ServerSession` is now a thin proxy (no longer a `BaseSession`)

`ServerSession` no longer subclasses `BaseSession`. It is now a small per-request proxy that exposes `send_request`, `send_notification`, the typed convenience helpers — `create_message`, `elicit` / `elicit_form` / `elicit_url`, `send_elicit_complete`, `list_roots`, `send_log_message`, `send_resource_updated`, `send_resource_list_changed` / `send_tool_list_changed` / `send_prompt_list_changed`, `send_ping`, `send_progress_notification`, and the new `report_progress` — plus `check_client_capability` and the read-only `client_params`, `client_capabilities`, `protocol_version`, and `can_send_request` properties. The receive loop, `initialize` handling, and per-request task isolation that previously lived in `ServerSession` have moved to `JSONRPCDispatcher` and `ServerRunner`.

The helpers keep their v1 signatures, so calls through `ctx.session` are source-compatible: `send_notification(notification, related_request_id=None)`, `send_log_message(level, data, logger=None, related_request_id=None)` (now [SEP-2577-deprecated](#roots-sampling-and-logging-methods-deprecated-sep-2577)), `send_progress_notification(progress_token, progress, total=None, message=None, related_request_id=None)`, `related_request_id=` on `elicit_form` / `elicit_url` / `send_elicit_complete`, and `metadata=ServerMessageMetadata(related_request_id=...)` on `send_request` (used by `create_message`). As in v1, a present `related_request_id` routes the message onto that request's own stream (the POST response in streamable HTTP) and an absent one uses the connection's standalone stream — the one 2026-era exception being `send_log_message`, whose delivery is gated and request-scoped by the spec there (see [Log messages are delivered only to requests that opt in](#log-messages-are-delivered-only-to-requests-that-opt-in)). Two adjustments: `send_resource_updated(uri)` accepts `str | AnyUrl`, and `send_notification` takes the notification model itself — the `types.ServerNotification(...)` wrapper is gone with the other `RootModel` unions (`await session.send_notification(types.ResourceListChangedNotification())`; see [Replace `RootModel` by union types with `TypeAdapter` validation](#replace-rootmodel-by-union-types-with-typeadapter-validation)).

Behavior changes:

- **A new `ServerSession` proxy is built for every inbound message.** In v1 one `ServerSession` lived for the whole connection, and servers commonly keyed per-client state on `ctx.session` identity (a `WeakKeyDictionary[ServerSession, ...]`, `id(ctx.session)`, a set of captured sessions to notify later). In v2 each request and notification gets a fresh proxy over the same connection, so those idioms silently misbehave: a session-keyed dict never finds an earlier key, and a broadcast set grows by one entry per request, sending duplicates. Key on something connection-stable instead — on stateful streamable HTTP the `mcp-session-id` request header names the transport session (read it via `ctx.headers` on `MCPServer` or `ctx.request.headers` in a lowlevel handler); on stdio there is one connection per process. The per-connection object the proxies share is `mcp.server.connection.Connection` (`state`, `session_id`, `exit_stack`), which is not currently reachable from `ctx`.
- **A captured `ctx.session` stays usable after the handler returns.** The proxy holds the connection, not the request, so a background task can keep calling `send_resource_updated()` / `send_tool_list_changed()` on it while the client stays connected; with `related_request_id` omitted these ride the standalone stream as in v1 — except on a 2026-era connection, where change notifications are dropped and belong on the subscription bus instead ([change notifications travel only on `subscriptions/listen` streams](#change-notifications-travel-only-on-subscriptionslisten-streams)). A request-scoped send is only meaningful while that request is in flight — once the handler returns, that stream is closed and the message is dropped with a debug log.
- **Notifications after the connection has closed are dropped instead of raising.** In v1 the notification helpers raised `anyio.ClosedResourceError`/`anyio.BrokenResourceError` on a dead connection, and broadcast loops used that exception to prune sessions. In v2 the send returns normally (the drop is debug-logged), so probe with a request instead: `await session.send_ping()` raises `MCPError` once the connection has closed. On a 2026-07-28 connection, though, every server-initiated request raises `NoBackChannelError` (an `MCPError`) regardless, so a ping is a liveness probe only on connections negotiated at 2025-11-25 or earlier.

`ServerSession` is normally constructed for you by `Server.run()` and reached via `ctx.session` in handlers, so beyond the behavior changes above, most servers are unaffected. If you were constructing or subclassing it directly:

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

Positional callers (`session.elicit_form(message, schema)`) are unaffected, and so are the return types: `elicit()`, `elicit_form()`, and `elicit_url()` still return `ElicitResult` (`action` of `"accept"`/`"decline"`/`"cancel"` plus `content`), and `create_message()` still returns `CreateMessageResult` (or `CreateMessageResultWithTools` when `tools`/`tool_choice` are passed). `elicit_url()` already used snake_case parameters in v1; only `elicit()` and `elicit_form()` changed.

## Clients

### `Client` defaults to `mode='auto'`

In v1, connecting to a server always performed the `initialize` handshake. In v2, `Client` defaults to `mode='auto'`: on enter it probes `server/discover` and, if the server doesn't support it, falls back to the `initialize` handshake. Pass `mode='legacy'` to force the initialize handshake and reproduce v1's pre-2026 connection sequence (the per-request wire shape still differs from v1; see [Every outbound request now carries a `_meta` envelope](#every-outbound-request-now-carries-a-_meta-envelope-opentelemetry-is-on-by-default)), or pass a modern protocol-version string (e.g. `mode='2026-07-28'`) to pin a version without probing.

The probe is transport-independent: v2 servers answer it over stdio (and any other stream-pair transport) as well as streamable HTTP, so `mode='auto'` lands on `2026-07-28` against a v2 server on every transport. If your stdio workflow relies on server-initiated requests (sampling, push elicitation, roots), pass `mode='legacy'` — a 2026-07-28 connection refuses them on every transport with `NoBackChannelError` (see [Server-initiated sampling, elicitation, and roots raise `NoBackChannelError`](#server-initiated-sampling-elicitation-and-roots-raise-nobackchannelerror)).

For an in-process `Client(server)` (where `server` is a `Server` or `MCPServer` instance), `mode='auto'` dispatches calls directly through `DirectDispatcher` with no JSON-RPC framing. Pass `mode='legacy'` if you need the in-memory JSON-RPC transport that v1 used — or if the server pushes sampling, elicitation, or roots requests, which the default 2026-07-28 in-process connection refuses with `NoBackChannelError` even when the matching callback is set (see the section linked above). `mode` is a `Client` argument only: a lowlevel `ClientSession` you `initialize()` yourself always performs the pre-2026 handshake, and `ClientSession.discover()` is the explicit 2026-07-28 entry point.

`Client.send_ping()` is deprecated (ping is removed in 2026-07-28) and emits `mcp.MCPDeprecationWarning` when called; pin `mode='legacy'` if you need it. The lowlevel `ClientSession.send_ping()` carries no deprecation marker.

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

On the high-level `Client`, `client.server_capabilities` and `client.protocol_version` are non-nullable inside the context manager. `client.instructions` remains `str | None` since the server may omit it, and `client.server_info` is `Implementation | None`: on 2026-era connections identity is optional wire metadata, so a server that does not report it reads as `None`. (The lowlevel `ClientSession` still lets you call methods before any handshake, as in v1; `Client` always connects on enter — by default it probes `server/discover` and falls back to the initialize handshake.)

### `cursor` parameter removed from `ClientSession` list methods

The deprecated `cursor` parameter has been removed from the following `ClientSession` methods:

- `list_resources()`
- `list_resource_templates()`
- `list_prompts()`
- `list_tools()`

Each method now takes a single keyword-only argument, `params: PaginatedRequestParams | None = None`. Pass `params=PaginatedRequestParams(cursor=...)` to continue from a `next_cursor`; omit `params` for the first page.

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

To walk every page, feed each result's `next_cursor` back in until it comes back `None`:

```python
tools = []
cursor = None
while True:
    page = await session.list_tools(params=PaginatedRequestParams(cursor=cursor))
    tools.extend(page.tools)
    if (cursor := page.next_cursor) is None:
        break
```

The high-level `Client` (including the `Client(server)` replacement described under [Testing utilities](#testing-utilities)) does not accept `params=` — passing it raises `TypeError`. Its list methods keep pagination as a plain keyword, `await client.list_tools(cursor="next_page_token")`, alongside `meta=` and a per-call `cache_mode=` (`"use"` by default, or `"refresh"`/`"bypass"`) for the client's built-in [response cache](client/caching.md); `client.session.list_tools(params=...)` reaches the underlying `ClientSession` if you want the `params` form.

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

A client request that exceeds `read_timeout_seconds` still raises the SDK's protocol error (`MCPError`, previously `McpError`), but the error code changed from the HTTP status `408` (`httpx.codes.REQUEST_TIMEOUT`) to the JSON-RPC code `-32001` (`REQUEST_TIMEOUT`, importable from `mcp.types`), matching the TypeScript SDK. The message changed too: v1 said `"Timed out while waiting for response to ClientRequest. Waited 5.0 seconds."`, v2 says `"Request 'tools/call' timed out"`. `MCPError.error` still exists, so a migrated `e.error.code == 408` check runs without error and silently never matches; timeouts fall through to whatever generic-error handling follows. Code that matched on the old message text breaks too. Compare against `REQUEST_TIMEOUT` instead.

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
from mcp.types import REQUEST_TIMEOUT  # -32001

try:
    result = await client.call_tool("slow_tool", {})
except MCPError as e:
    if e.code == REQUEST_TIMEOUT:
        ...  # retry / back off
    else:
        raise
```

`e.error.code` also still works; `e.code` is the v2 convenience property. The constant is importable from `mcp.types` (or from `mcp_types` in a project that uses that package without the SDK). The example uses the high-level `Client`; `ClientSession.call_tool()` raises the same `MCPError`.

### `ClientSession` now runs on `JSONRPCDispatcher`; `BaseSession` removed

`ClientSession`'s public surface is unchanged — same constructor apart from timeout parameters (see [Timeouts take `float` seconds instead of `timedelta`](#timeouts-take-float-seconds-instead-of-timedelta)), typed methods, manual `initialize()`, and async context-manager lifecycle — but `BaseSession`, the v1 receive loop underneath it, is removed with no shim. The engine now lives in `JSONRPCDispatcher` (`mcp.shared.jsonrpc_dispatcher`). To customize client behavior, use the `ClientSession` constructor callbacks, or pass a pre-built dispatcher via the new keyword-only `dispatcher=` constructor argument (e.g. a `DirectDispatcher` for in-process embedding). Passing one of the SDK's own dispatchers (`JSONRPCDispatcher`, or `DirectDispatcher` from `mcp.shared.direct_dispatcher`) is the supported use; the `Dispatcher` protocol's `run()` lifecycle (`mcp.shared.dispatcher`) is documented as provisional, so treat a hand-written implementation as experimental.

Behavior changes:

- **Callbacks and notifications now run concurrently.** In v1 the receive loop processed one inbound message at a time, so callbacks ran inline and in order. Now each delivery starts in arrival order but runs as its own task. Server-initiated request callbacks (`sampling`, `elicitation`, `roots`) no longer block other traffic, may themselves send requests without deadlocking, and are interrupted if the server sends `notifications/cancelled` (no response is sent for the cancelled request). Notification callbacks (`logging_callback`, `progress_callback`, `message_handler`) may interleave, and a `progress_callback` may run after the request it reports on has returned; there is no built-in bound on concurrent deliveries. Transport-level errors reach `message_handler` the same way, and a `message_handler` that raises is logged rather than fatal to the session. Callbacks that need strict sequencing must coordinate themselves.
- **Notification routing is unchanged.** Each server notification is still delivered to its typed callback first — `logging_callback` for log messages, the per-request `progress_callback` whose `progressToken` matches a request you issued (`progress_callback=` still stamps `params._meta.progressToken` with the outbound request id) — and then teed to `message_handler`. `notifications/cancelled` is applied by the dispatcher and never surfaced, also as in v1.
- **Cancellation now reaches the server.** Cancelling the task or cancel scope awaiting a request (e.g. `anyio.move_on_after()` around `session.call_tool(...)`), or a request hitting its read timeout, now sends `notifications/cancelled` for that request, so the server interrupts the handler instead of leaving it running; v1 sent nothing ([#2507](https://github.com/modelcontextprotocol/python-sdk/issues/2507)). A test that pinned the v1 gap with a strict `xfail` now passes — drop the marker. The cancelled peer no longer answers at all (v1 sent `ErrorData(code=0, message="Request cancelled")`); the one exception, the 2025-era streamable HTTP transport's `-32800` terminator, is discarded like the v1 error since the caller's waiter is already gone — see [Cancelled requests are no longer answered](#cancelled-requests-are-no-longer-answered). There is no public request-id or cancel handle (v1's private `session._request_id` went with `BaseSession`): cancel the awaiting task or scope and the dispatcher sends the cancel for you.
- **A raising request callback** is answered with `code=0` and the exception text; v1 flattened every callback exception to `INVALID_PARAMS`. For a specific error response, return `ErrorData` (unchanged) or raise `MCPError`. One carve-out: pydantic's `ValidationError` is still answered with `INVALID_PARAMS`, as in v1.
- **`send_request` before entering the context manager** raises `RuntimeError` immediately; v1 wrote to the transport and hung until the timeout. After the connection has closed it raises `MCPError` (`CONNECTION_CLOSED`) instead. `send_notification` before entry still works.
- **`send_notification` after the connection has closed is dropped with a debug log instead of raising.** In v1 the send raised `anyio.BrokenResourceError` (peer gone) or `anyio.ClosedResourceError` (session torn down), and this applied to the typed helpers (`send_roots_list_changed`, `send_progress_notification`) too. Code that used the exception as its disconnect signal should probe with a request instead (`send_request` still raises `MCPError` after close, see above) or scope the sending task to the session's lifetime.
- **`send_notification` no longer takes `related_request_id`, and `send_request` no longer accepts `ServerMessageMetadata`.** No client transport ever serialized these hints; progress and response correlation via `progressToken` and the request id is unaffected. This is client-side only: the server's `ServerSession` helpers keep `related_request_id` (see [`ServerSession` is now a thin proxy](#serversession-is-now-a-thin-proxy-no-longer-a-basesession)).
- **Client callbacks now receive `mcp.client.ClientRequestContext`** (its `request_id` is always populated); the `mcp.shared.context.RequestContext` generic is deleted. Annotations spelled `RequestContext[ClientSession, Any]` become `ClientRequestContext` (details in [`RequestContext` type parameters simplified](#requestcontext-type-parameters-simplified)). Otherwise the callback surface is unchanged: the `sampling_callback=`, `elicitation_callback=`, `list_roots_callback=`, `logging_callback=`, and `message_handler=` keywords; the `SamplingFnT`, `ElicitationFnT`, `ListRootsFnT`, `LoggingFnT`, and `MessageHandlerFnT` protocols (still in `mcp.client.session`); and the params/result types (`CreateMessageRequestParams` → `CreateMessageResult | CreateMessageResultWithTools | ErrorData`, `ElicitRequestParams` → `ElicitResult | ErrorData`, `ListRootsResult | ErrorData` — returning `ErrorData` is not new). The `mcp.client.session`, `mcp.client.stdio`, `mcp.client.sse`, and `mcp.client.streamable_http` module paths are unchanged too, so `unittest.mock.patch` string targets still resolve.
- **`message_handler` no longer receives requests.** Server-initiated requests are answered by the typed callbacks (`sampling_callback`, `elicitation_callback`, `list_roots_callback`), so the handler's parameter is now `IncomingMessage = ServerNotification | Exception`, exported from `mcp.client`. Replace the hand-written v1 union `RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception` with `IncomingMessage`; `RequestResponder` is gone (below), so the old annotation no longer imports. Delivered notifications are the concrete member instances rather than the v1 `RootModel` wrapper, so drop `.root` (`message.params`, not `message.root.params`); see [Replace `RootModel` by union types with `TypeAdapter` validation](#replace-rootmodel-by-union-types-with-typeadapter-validation).

The `mcp.shared.session` module is gone. `RequestResponder` is removed — `respond()`, the cancellation-tracking members (`cancel()`, the `cancelled` and `in_flight` properties, the `on_complete` constructor argument) and `BaseSession._in_flight` have no replacement; inbound cancellation is handled by `JSONRPCDispatcher`. `ProgressFnT` now lives only in `mcp.shared.dispatcher`, and `RequestId` in `mcp.types`. The module's generic typing helpers (`SendRequestT`, `SendResultT`, `SendNotificationT`, `ReceiveRequestT`, `ReceiveResultT`, `ReceiveNotificationT`) went with it and have no re-export — the sessions are no longer generic; `ClientSession.send_request` takes a concrete request model plus a result model class (or `pydantic.TypeAdapter`), so an override that needs a type parameter can declare its own `TypeVar` bound to `pydantic.BaseModel`.

Subclassing `ClientSession` remains a valid interception point: every typed helper routes through `send_request`, and the notification helpers through `send_notification`, so overriding those two still sees that traffic (the 2026-era `discover()`/`send_discover()` are the exception — they call the dispatcher directly). For wire-level interception, use the `dispatcher=` argument instead (with the caveat above on hand-written dispatchers).

Migrating a request callback is a signature-only change (sampling and roots callbacks have the same shape):

**Before (v1):**

```python
async def elicitation_callback(
    context: RequestContext[ClientSession, Any], params: types.ElicitRequestParams
) -> types.ElicitResult | types.ErrorData: ...
```

**After (v2):**

```python
from mcp.client import ClientRequestContext
from mcp.types import ElicitRequestParams, ElicitResult, ErrorData


async def elicitation_callback(
    context: ClientRequestContext, params: ElicitRequestParams
) -> ElicitResult | ErrorData: ...
```

### Experimental Tasks support removed

Tasks ([SEP-1686](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1686)) have been removed from the MCP specification and are no longer part of this SDK. The `mcp.client.experimental`, `mcp.server.experimental`, `mcp.shared.experimental`, and `mcp.server.lowlevel.experimental` modules have been removed, along with the `experimental` properties on `ClientSession`, `ServerSession`, `Server`, and `ServerRequestContext`. The corresponding `Task*` types remain in `mcp.types` as types-only definitions, except the `TaskExecutionMode` alias, whose literal is now inlined on `ToolExecution.task_support`.

The 2026-07-28 revision reintroduces Tasks as an official extension: [SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2663), `io.modelcontextprotocol/tasks`, redesigned around polling (`tasks/get`) instead of a blocking `tasks/result`. This SDK does not implement the extension yet.

There is no drop-in replacement for the tasks runtime (`server.experimental.enable_tasks()`, `ctx.experimental.run_task()`, `ServerTaskContext`, and the client's `session.experimental.call_tool_as_task()` / `poll_task()` / `get_task_result()`); the port depends on what the code used tasks for.

**Status updates on a long-running tool.** Run the work inline in the tool handler and replace `ServerTaskContext.update_status()` with progress reporting: `ctx.report_progress(progress, total, message)` on `MCPServer`, or `ctx.session.report_progress(...)` in a lowlevel handler (a no-op when the caller did not request progress). The client no longer creates a task and polls `tasks/get`; it passes `progress_callback=` to `call_tool()` and receives `notifications/progress` while the single call is in flight.

**Before (v1):**

```python
# server: hand the work to the task runtime and report status from inside it
async def work(task: ServerTaskContext) -> types.CallToolResult:
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
# server
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

**Gathering user input mid-work** (`task.elicit()`, `task.create_message()`). Don't port these to inline `ctx.elicit()` / `ctx.session.create_message()` calls: those are server-initiated requests, refused with `NoBackChannelError` on 2026-07-28 connections (the default for an in-process `Client(server)`). Use the resolver dependencies (`Elicit`, `Sample`) or return an `InputRequiredResult` — both work on every protocol version, and `Client.call_tool()` retries the `InputRequiredResult` rounds automatically; see [Multi-round-trip requests](handlers/multi-round-trip.md) and [Server-initiated sampling, elicitation, and roots raise `NoBackChannelError`](#server-initiated-sampling-elicitation-and-roots-raise-nobackchannelerror). The client's existing `elicitation_callback` / `sampling_callback` serve both eras.

**Detached work** (create the task now, fetch its result on a later connection or after a client restart) has no v2 equivalent until the SEP-2663 extension is implemented.

Also drop `execution=ToolExecution(taskSupport=types.TASK_REQUIRED)` from tool definitions: the `TASK_REQUIRED` / `TASK_OPTIONAL` / `TASK_FORBIDDEN` constants are gone from `mcp.types` (`ToolExecution.task_support` takes the plain `"required"` / `"optional"` / `"forbidden"` literal), and no v2 client or server reads the field.

## Transports

Server-side transport entry points (`stdio_server()`, `SseServerTransport`, `StreamableHTTPSessionManager`) keep their v1 import paths and signatures (see [Lowlevel `Server`: what did not change](#lowlevel-server-what-did-not-change)), so the sections below are client-side apart from [`stdio_server` keeps the protocol streams on private descriptors](#stdio_server-keeps-the-protocol-streams-on-private-descriptors); the other server-side transport changes ([lifespan entered once](#streamable-http-lifespan-now-entered-once-at-manager-startup), the [4 MiB request-body limit](#streamable-http-request-bodies-are-limited-to-4-mib)) sit under MCPServer.

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
import httpx2
from mcp.client.streamable_http import streamable_http_client

# Configure headers, timeout, and auth on the httpx2.AsyncClient
http_client = httpx2.AsyncClient(
    headers={"Authorization": "Bearer token"},
    timeout=httpx2.Timeout(30, read=300),
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

v1's internal client set `follow_redirects=True`; set it explicitly when supplying your own `httpx2.AsyncClient` to preserve that behavior.

`streamable_http_client` itself keeps a small signature — `streamable_http_client(url, *, http_client=None, terminate_on_close=True)` — and now yields a 2-tuple (next section). The removed function's other parameters map onto the client you build:

- `headers`, `timeout`, `sse_read_timeout`, `auth`: set them on the `httpx2.AsyncClient` as above. `streamablehttp_client` defaulted to `httpx.Timeout(30, read=300)`; a bare `httpx2.AsyncClient()` falls back to httpx2's flat 5-second timeout, too short for the long-lived GET stream, so set `timeout=httpx2.Timeout(30, read=300)` (as shown) to keep v1's values. Omitting `http_client` still gives you a default client with those timeouts and `follow_redirects=True`.
- `httpx_client_factory`: gone with no replacement — call your factory yourself and pass the result as `http_client`.
- `terminate_on_close`: unchanged (default `True`).

Client-side stream resumption is also unchanged: the transport reconnects a dropped GET stream with `Last-Event-ID` on its own, and `session.send_request(..., metadata=ClientMessageMetadata(resumption_token=..., on_resumption_token_update=...))` (from `mcp.shared.message`) works as in v1.

### `get_session_id` callback removed from `streamable_http_client`

The `get_session_id` callback (third element of the returned tuple) has been removed from `streamable_http_client`. The function now returns a 2-tuple `(read_stream, write_stream)` instead of a 3-tuple.

The `GetSessionIdCallback` type alias is gone as well, so `from mcp.client.streamable_http import GetSessionIdCallback` now raises `ImportError`. Drop the annotation, or inline `Callable[[], str | None]` if your own wrapper code still needs the type. The `StreamableHTTPTransport.get_session_id()` method that backed the callback is removed too.

If you need to capture the session ID (e.g., for session resumption testing), you can use httpx2 event hooks to capture it from the response headers:

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
import httpx2
from mcp.client.streamable_http import streamable_http_client

# Option 1: Simply ignore if you don't need the session ID
async with streamable_http_client(url) as (read_stream, write_stream):
    async with ClientSession(read_stream, write_stream) as session:
        await session.initialize()

# Option 2: Capture session ID via httpx2 event hooks if needed
captured_session_ids: list[str] = []

async def capture_session_id(response: httpx2.Response) -> None:
    session_id = response.headers.get("mcp-session-id")
    if session_id:
        captured_session_ids.append(session_id)

http_client = httpx2.AsyncClient(
    event_hooks={"response": [capture_session_id]},
    follow_redirects=True,
)

async with http_client:
    async with streamable_http_client(url, http_client=http_client) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            session_id = captured_session_ids[0] if captured_session_ids else None
```

The hook fires on every response the client sees, so `captured_session_ids` gains one entry per response carrying an `mcp-session-id` header (all the same value on one connection; if you reuse an `httpx2.AsyncClient` across reconnects, take the last entry). A hook can also be appended to an existing client: `client.event_hooks["response"].append(capture_session_id)`.

`terminate_on_close` still defaults to `True`, so `streamable_http_client` sends its own `DELETE` for the session on exit; if your test deletes the session itself, pass `terminate_on_close=False`, or the transport's follow-up `DELETE` hits an already-terminated session and logs a `Session termination failed: 404` warning.

### `StreamableHTTPTransport` parameters removed

The `headers`, `timeout`, `sse_read_timeout`, and `auth` parameters have been removed from `StreamableHTTPTransport`. Configure these on the `httpx2.AsyncClient` instead (see example above).

`sse_client` is unchanged apart from the `httpx2` retyping: it still takes `url`, `headers`, `timeout`, `sse_read_timeout`, `httpx_client_factory` (which must now return an `httpx2.AsyncClient`), `auth` (now `httpx2.Auth | None`), and `on_session_created`. Only the streamable HTTP transport dropped its transport-level parameters; `StreamableHTTPTransport(url)` now takes just the URL.

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
from mcp.types import INVALID_REQUEST  # -32600

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

Move HTTP-status failure handling from around the transport context to around the individual calls, catching `MCPError` (see [`McpError` renamed to `MCPError`](#mcperror-renamed-to-mcperror)). Connect-level failures such as `httpx2.ConnectError` still escape the transport context as before; keep context-level handling for those only.

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

### `stdio_server` keeps the protocol streams on private descriptors

While serving, the stdio transport moves the wire to private descriptors and points
fd 0 at the null device and fd 1 at stderr, restoring both on exit. Subprocesses and
handler code can no longer read protocol bytes or write into the stream (the
[#671](https://github.com/modelcontextprotocol/python-sdk/issues/671) fix). Ordinary
servers have nothing to do, and code that inspects or manipulates fd 0/1 directly
during a session now sees the diversions, not the wire.

One pattern needs migrating: watchdog threads that watch fd 0 to detect a vanished
client (a POSIX-specific pattern; `select.poll` does not exist on Windows). The null
device does not behave like the old pipe: it never reports `POLLHUP` or `POLLERR`,
and it reports readable immediately and permanently (`POLLIN` from `poll()` on Linux,
plus `POLLOUT` under the default event mask; ready from `select()`; and macOS can
report `POLLNVAL` for devices). A watcher waiting for `POLLHUP` or `POLLERR` is
silently disarmed; a watcher that treats any event as "client gone" now fires at
startup instead of never. Watch the parent process instead: on POSIX, exit
when `os.getppid()` changes, which happens when the client dies because orphaned
processes are reparented. That works on both v1 and v2 and does not depend on
descriptor layout.

Also new: a second concurrent `stdio_server()` on the process's default streams now
raises `RuntimeError` instead of silently contending for stdin, a configuration that
never worked (there is one stdin).

Also worth knowing: a child process that streams large output to its inherited
stdout now streams it into the client's stderr channel. Capture output you do not
want in the client's logs, and be aware that a client which never drains its stderr
pipe applies back-pressure to the server (true of stderr logging on v1 as well).

### WebSocket transport removed

The WebSocket transport has been removed: `mcp.client.websocket.websocket_client`, `mcp.server.websocket.websocket_server`, and the `ws` optional dependency extra (`mcp[ws]`) no longer exist. WebSocket was never part of the MCP specification. Use the streamable HTTP transport instead (`mcp.client.streamable_http.streamable_http_client` on the client, `streamable_http_app()` on the server), which supports bidirectional communication with server-to-client streaming over standard HTTP.

## OAuth and server auth

### Unchanged auth surfaces

Most of the auth API carries over from v1; if a survey of your `mcp.client.auth` /
`mcp.server.auth` usage only turns up the changes documented in the sections below, that is
expected. In particular:

- **OAuth client core.** `OAuthClientProvider` keeps its v1 constructor apart from the
  [removed `timeout`](#timeout-parameter-removed-from-oauthclientprovider) and the
  [`AuthorizationCodeResult`-returning `callback_handler`](#oauth-callback_handler-returns-authorizationcoderesult),
  and gains an optional `validate_resource_url` callback for overriding the RFC 8707 resource
  check: `OAuthClientProvider(server_url, client_metadata, storage, redirect_handler=None,
  callback_handler=None, client_metadata_url=None, validate_resource_url=None)`. `PKCEParameters`,
  `TokenStorage`, and the exceptions exported by `mcp.client.auth` (`OAuthFlowError`,
  `OAuthTokenError`, `OAuthRegistrationError`) are unchanged; import `OAuthTokenError` from
  `mcp.client.auth`, since `mcp.client.auth.extensions.client_credentials` no longer happens to
  re-export it. `provider.context` (`OAuthContext`: `current_tokens`, `token_expiry_time`,
  `is_token_valid()`, `can_refresh_token()`, `clear_tokens()`) also carries over, but remains an
  internal object with no stability guarantee.
- **Client-credentials extension.** `ClientCredentialsOAuthProvider`,
  `PrivateKeyJWTOAuthProvider`, `SignedJWTParameters`, and `static_assertion_provider` in
  `mcp.client.auth.extensions.client_credentials` keep their v1 signatures apart from the
  [`scopes=` → `scope=` rename](#scopes-renamed-to-scope-on-the-client-credentials-providers)
  and the [`RFC7523OAuthClientProvider`/`JWTParameters` removal](#rfc7523oauthclientprovider-and-jwtparameters-removed).
  Their base class is now `httpx2.Auth` (see
  [`httpx` and `httpx-sse` replaced by `httpx2`](#httpx-and-httpx-sse-replaced-by-httpx2)),
  and `token_endpoint_auth_method="client_secret_post"` changes the token request body (see
  [`client_secret_post` token requests now include `client_id`](#client_secret_post-token-requests-now-include-client_id)).
- **Discovery and registration helpers.** `mcp.client.auth.utils` keeps its v1 helpers
  (`build_protected_resource_metadata_discovery_urls`,
  `build_oauth_authorization_server_metadata_discovery_urls`, the `handle_*_response`
  coroutines, `extract_field_from_www_auth`/`extract_scope_from_www_auth`,
  `get_client_metadata_scopes`), retyped from `httpx` to `httpx2` request/response objects.
  The additions — `union_scopes`, `validate_metadata_issuer`,
  `validate_authorization_response_iss`, `credentials_match_issuer`, and an optional
  `client_grant_types` on `get_client_metadata_scopes` — are new, not renames.
- **Resource-server surface.** `TokenVerifier`, `AccessToken`, and
  `OAuthAuthorizationServerProvider` (`mcp.server.auth.provider`), `AuthSettings`,
  `create_auth_routes`/`create_protected_resource_routes`,
  `BearerAuthBackend`/`RequireAuthMiddleware`, `AuthContextMiddleware`/`get_access_token`,
  `mcp.shared.auth`, `mcp.shared.auth_utils`, and `MCPServer`'s
  `auth=`/`auth_server_provider=`/`token_verifier=` keywords all carry over. `AccessToken` has
  had optional `subject` and `claims` fields since v1.27.2, so a subclass that existed only to
  add them can be dropped. The SDK-hosted authorization server changes only per
  [Stricter client authentication at `/token` and `/revoke`](#stricter-client-authentication-at-token-and-revoke),
  plus the additive [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990)
  identity-assertion pieces (`AuthSettings(identity_assertion_enabled=True)` /
  `create_auth_routes(..., identity_assertion_enabled=True)` and the overridable
  `OAuthAuthorizationServerProvider.exchange_identity_assertion`, which rejects the grant by
  default). The `mcp.shared.auth` metadata models keep their fields, with the additions covered
  in the sections below.

### `RFC7523OAuthClientProvider` and `JWTParameters` removed

`RFC7523OAuthClientProvider` (deprecated since 1.23.0) and its `JWTParameters` model have been
removed from `mcp.client.auth.extensions.client_credentials`. The provider implemented the
[RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) §2.1 `jwt-bearer` *authorization grant*
with an SDK-minted or prebuilt JWT, which no MCP auth extension specifies. Replace it with the
purpose-built provider for the flow you actually run:

- Machine-to-machine with a client secret
  ([`io.modelcontextprotocol/oauth-client-credentials`](https://modelcontextprotocol.io/extensions/auth/oauth-client-credentials)):
  `ClientCredentialsOAuthProvider(server_url=..., storage=..., client_id=..., client_secret=...)`.
- Machine-to-machine authenticating with a JWT instead of a secret (same extension, RFC 7523 §2.2
  `private_key_jwt` client authentication on the `client_credentials` grant, which is the mode the
  extension actually specifies for JWTs): `PrivateKeyJWTOAuthProvider(server_url=...,
  storage=..., client_id=..., assertion_provider=...)`. Build the assertion with
  `SignedJWTParameters(issuer=..., subject=..., signing_key=...).create_assertion_provider()`
  (replaces `JWTParameters` signing fields), or wrap a prebuilt JWT with
  `static_assertion_provider(token)` (replaces `JWTParameters(assertion=...)`).
- Presenting an enterprise ID-JAG under the `jwt-bearer` grant
  ([SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990)):
  `IdentityAssertionOAuthProvider` in `mcp.client.auth.extensions.identity_assertion`.

The provider's third mode — the interactive `authorization_code` flow with `private_key_jwt`
client authentication on the token exchange — has no replacement and is intentionally dropped; it
was never exercised by the test suite and no MCP auth extension specifies it. If you depended on
it, open an issue describing the deployment.

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

### `scopes=` renamed to `scope=` on the client-credentials providers

`ClientCredentialsOAuthProvider` and `PrivateKeyJWTOAuthProvider` took the requested scope as a keyword named `scopes`, even though the value is a single space-separated string, not a list. The parameter is now `scope`, matching the RFC 6749 wire parameter, `OAuthClientMetadata.scope`, and the newer `IdentityAssertionOAuthProvider`.

**Before (v1):**

```python
ClientCredentialsOAuthProvider(..., scopes="read write")
```

**After (v2):**

```python
ClientCredentialsOAuthProvider(..., scope="read write")
```

### `client_secret_post` token requests now include `client_id`

With `token_endpoint_auth_method="client_secret_post"`, the token request body now carries both `client_id` and `client_secret`, as [RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749) §2.3.1 requires; v1 sent only `client_secret`. The authorization-code and refresh requests already carried `client_id`, so the observable difference is the `client_credentials` exchange sent by `ClientCredentialsOAuthProvider(..., token_endpoint_auth_method="client_secret_post")` (plus `resource`/`scope` when configured):

```text
# v1
grant_type=client_credentials&client_secret=SECRET
# v2
grant_type=client_credentials&client_id=CLIENT_ID&client_secret=SECRET
```

Authorization servers that require both parameters answered the v1 request with `401 invalid_client`, so under v1 this provider effectively only worked with the default `client_secret_basic`. Drop any manual `client_id` injection or a test that pinned the 401 — the exchange now succeeds as configured.

### `timeout` parameter removed from `OAuthClientProvider`

`OAuthClientProvider` no longer accepts a `timeout` argument, and `OAuthContext.timeout` is gone. The value was stored but never read, so it never bounded anything — removing it changes nothing at runtime.

**Before (v1):**

```python
provider = OAuthClientProvider(server_url, client_metadata, storage, timeout=120.0)
```

**After (v2):**

```python
provider = OAuthClientProvider(server_url, client_metadata, storage)
```

If you passed `timeout` to bound how long you wait for the user to complete authorization, apply that bound where you actually wait — inside your `redirect_handler`/`callback_handler`, e.g. `with anyio.fail_after(120): ...`. The full v2 constructor (v1's parameters minus `timeout`, plus a new optional `validate_resource_url` callback) is listed under [Unchanged auth surfaces](#unchanged-auth-surfaces).

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

### `OAuthClientInformationFull` no longer subclasses `OAuthClientMetadata`, and parses server-substituted metadata

`OAuthClientMetadata` is the registration request a client sends; `OAuthClientInformationFull` is the authorization server's record of a registered client, parsed from its Dynamic Client Registration response. In v1 the second inherited from the first, which typed the response as though it had to be a request this SDK would send. It does not: [RFC 7591 §3.2.1](https://datatracker.ietf.org/doc/html/rfc7591#section-3.2.1) lets the server "reject or replace any of the client's requested metadata values submitted during the registration and substitute them with suitable values", and real servers return an `application_type` outside OIDC Registration's `web`/`native`, an explicit `null`, a `token_endpoint_auth_method` the SDK does not implement, or an empty `redirect_uris`. The inherited strict types turned each of those into a `ValidationError` on a 2xx response - after the server had already provisioned the client, so the registration was discarded and orphaned.

The two are now siblings over a shared `OAuthClientMetadataBase`. `OAuthClientMetadata` keeps its strict types (the SDK still refuses to *send* an unregistered `application_type`), while `OAuthClientInformationFull` accepts what a server may echo:

```python
# v1
class OAuthClientInformationFull(OAuthClientMetadata): ...

# v2
class OAuthClientMetadata(OAuthClientMetadataBase): ...          # request: strict
class OAuthClientInformationFull(OAuthClientMetadataBase): ...   # server record: tolerant
```

On `OAuthClientInformationFull`, `application_type` and `token_endpoint_auth_method` are now `str | None`, `grant_types` is `list[str]`, and `redirect_uris` is optional (`list[AnyUrl] | None`, no minimum length). `client_id` is now required (`str`): [RFC 7591 §3.2.1](https://datatracker.ietf.org/doc/html/rfc7591#section-3.2.1) makes it mandatory in the response, and a record of a registered client without one was never meaningful. Code that only reads these fields is unaffected. Code that relied on `isinstance(client_info, OAuthClientMetadata)`, or passed an `OAuthClientInformationFull` where an `OAuthClientMetadata` is expected, must reference the record type directly. `validate_scope()` and `validate_redirect_uri()` moved with the record: they are methods of `OAuthClientInformationFull` (the type authorization-server code holds) and are no longer available on `OAuthClientMetadata`.

A registration response the server sends is no longer rejected on these fields: a member serialized as a placeholder - an explicit `null`, or `""` - reads as an omitted key, so its default applies. Whether a substituted value is usable is judged where it matters, not at parse. When Dynamic Client Registration completes with credentials the authorization-code flow cannot use - a `token_endpoint_auth_method` other than `none`, `client_secret_post`, or `client_secret_basic` (including `private_key_jwt`, whose assertion that flow has no key to sign), or a secret-based method for which the server issued no `client_secret` - the client raises `OAuthRegistrationError` naming the problem, before the record is stored or authorization begins. Separately, a stored or pre-registered record carrying a method the SDK does not know at all raises `OAuthTokenError` when it reaches the token exchange; `private_key_jwt` on such a record does not raise there, so `PrivateKeyJWTOAuthProvider`, which signs its assertion only in the client-credentials exchange, still recovers from a rejected refresh by exchanging afresh.

The SDK's own registration endpoint now returns all registered metadata in its 201 response (RFC 7591 §3.2.1) - including the client's `application_type`, which v1 dropped from the echo (silently reporting the default in place of a client's `"web"`), and `client_secret_expires_at` (`0` when the secret never expires) whenever a `client_secret` is issued. It also now answers a `private_key_jwt` registration with `400 invalid_client_metadata` rather than confirming a method it authenticates no requests with.

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

Validation runs when the result is serialized onto the wire, not when the model is constructed: `Tool(name="t", input_schema={})` still constructs, so a fixture that builds such a tool only fails once a `tools/list` handler returns it. Your handler returns normally; the server then logs the `pydantic.ValidationError` (`handler for 'tools/list' returned an invalid result`) and answers the request with `INTERNAL_ERROR`, so the failure shows up on the client, not at the line that built the model.

### Client validates inbound traffic against the protocol schema

`ClientSession` now validates server requests, notifications, and results against the negotiated protocol version's schema before parsing them into `mcp.types` models. Spec-invalid server output that the previous monolith parse tolerated may now raise `pydantic.ValidationError` from `list_tools()`, `call_tool()`, and similar calls. `_meta` remains the sanctioned place for result extras (and `experimental` for capability extras).

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

`Client` accepts the same callback parameters the old helper did (`sampling_callback`, `list_roots_callback`, `logging_callback`, `message_handler`, `elicitation_callback`, `client_info`), keeps `raise_exceptions` for surfacing server-side errors and `read_timeout_seconds` (now a plain `float` of seconds rather than a `timedelta`; see [Timeouts take `float` seconds instead of `timedelta`](#timeouts-take-float-seconds-instead-of-timedelta)), and adds `mode` to control version negotiation (`'auto'` by default; `'legacy'` reproduces v1's initialize-only handshake). Its method signatures are not identical to `ClientSession`'s: the `list_*()` methods paginate with a plain `cursor=` keyword rather than `params=PaginatedRequestParams(...)` (see [`cursor` parameter removed from `ClientSession` list methods](#cursor-parameter-removed-from-clientsession-list-methods)).

One consequence to plan for: unlike the old helper, `Client(server)` negotiates 2026-07-28 by default, where server-initiated requests are refused. A v1 test that drove `ctx.elicit()`, `ctx.session.create_message()`, or `list_roots()` through the helper now fails with `NoBackChannelError` even with the callbacks set. Pin the era — `Client(server, mode="legacy", sampling_callback=..., elicitation_callback=..., list_roots_callback=...)` — or port the handler to a resolver dependency; see [Server-initiated sampling, elicitation, and roots raise `NoBackChannelError`](#server-initiated-sampling-elicitation-and-roots-raise-nobackchannelerror).

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

Every deprecation below is a runtime warning as well as a type-checker one: deprecated methods and helpers emit `mcp.MCPDeprecationWarning` on each call, and the deprecated `Server(...)` constructor parameters (`on_set_logging_level`, `on_roots_list_changed`, `on_progress`) emit it at construction time. The category subclasses `UserWarning`, not `DeprecationWarning`, so it is visible by default; [Deprecated features](deprecated.md) has the full list and each replacement.

Under pytest's `filterwarnings = ["error"]`, that warning becomes an exception at the first deprecated call. Inside an `@mcp.tool()` handler the exception is caught like any other and returned as `CallToolResult(is_error=True)` (`Error executing tool ...: The logging capability is deprecated as of 2026-07-28 (SEP-2577).`), which reads as a failing tool rather than a warning. Keep the warnings visible but non-fatal with:

```toml
[tool.pytest.ini_options]
filterwarnings = [
    "error",
    "default::mcp.MCPDeprecationWarning",
]
```

Use `"ignore::mcp.MCPDeprecationWarning"` (or the `warnings.filterwarnings` call [below](#roots-sampling-and-logging-methods-deprecated-sep-2577)) to silence them instead, and wrap a test that deliberately exercises a deprecated path in `pytest.warns(MCPDeprecationWarning)`.

### Client resource-subscription methods deprecated (SEP-2575)

[SEP-2575](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2575) removes `resources/subscribe` and `resources/unsubscribe` from the 2026-07-28 wire; per-URI subscriptions travel in the `subscriptions/listen` filter instead. The client verbs now carry `typing_extensions.deprecated`:

- `Client.subscribe_resource()` / `Client.unsubscribe_resource()`
- `ClientSession.subscribe_resource()` / `ClientSession.unsubscribe_resource()`

Calling them emits `mcp.MCPDeprecationWarning`. They keep working against 2025-era servers — where they are still the only way to watch a resource, so code that talks to 2025-11-25 (or earlier) servers should keep calling them and filter the warning rather than migrate. A 2026-07-28 server answers them with `-32601` (method not found); on those connections migrate to the listen driver, `Client.listen()`:

```python
async with client.listen(resource_subscriptions=["board://sprint"]) as sub:
    async for event in sub:  # ResourceUpdated(uri="board://sprint")
        ...
```

On a bare `ClientSession` (no high-level `Client`), the same stream is `listen(session, resource_subscriptions=[...])` from `mcp.client.subscriptions` — the function `Client.listen()` wraps — which requires a 2026-07-28 connection and raises `ListenNotSupportedError` on an older one. See the [Subscriptions](client/subscriptions.md#watching-the-stream) page under Clients for the full client-side contract (typed events, the honored filter, clean end vs `SubscriptionLost`).

### Roots, Sampling, and Logging methods deprecated (SEP-2577)

[SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) deprecates the Roots, Sampling, and Logging features as of the 2026-07-28 spec. The deprecation is advisory only: there are no wire-level changes, capability negotiation is unchanged, and every method keeps working for sessions negotiating 2025-11-25 and earlier.

The deprecation and the back-channel are separate axes. Sampling, roots, and push elicitation are server-initiated *requests*, so on a connection negotiated at 2026-07-28 — including the default in-process `Client(server)` — `create_message()`, `list_roots()`, and `elicit()` / `elicit_form()` raise `NoBackChannelError` rather than working with a warning; the resolver markers `Sample`, `ListRoots`, and `Elicit` are the era-portable form (see [Server-initiated sampling, elicitation, and roots raise `NoBackChannelError`](#server-initiated-sampling-elicitation-and-roots-raise-nobackchannelerror)).

The user-facing methods for these features now carry `typing_extensions.deprecated`, so type checkers, IDEs, and the runtime surface a deprecation warning where they are called:

- Sampling: `ServerSession.create_message()`, `ClientPeer.sample()`
- Roots: `ServerSession.list_roots()`, `ClientPeer.list_roots()`, `ClientSession.send_roots_list_changed()`, `Client.send_roots_list_changed()`
- Logging: `ServerSession.send_log_message()`, `Connection.log()`, `ClientSession.set_logging_level()`, `Client.set_logging_level()`, `mcp.server.context.Context.log()` (the lowlevel `Context`), and the `MCPServer` `Context` helpers `log()`, `debug()`, `info()`, `warning()`, `error()`

Registering a handler for a deprecated capability is deprecated too. The `Server.__init__` parameters `on_set_logging_level` (Logging) and `on_roots_list_changed` (Roots) are now split out into a `typing_extensions.deprecated` overload, so passing either is flagged by type checkers and emits `mcp.MCPDeprecationWarning` at construction time. `on_progress` follows the same pattern (see below). The non-deprecated overload omits these parameters, so the common case stays warning-free.

To silence the warnings in code, filter the category:

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
earlier) peers is unaffected — the notable exception being an in-process `Client(server)`,
which negotiates 2026-07-28 by default (first subsection below). It is collected here so the
rest of this guide stays focused on the v1-to-v2 upgrade itself.

### Server-initiated sampling, elicitation, and roots raise `NoBackChannelError`

The 2026-07-28 protocol has no server-initiated requests, so a handler that reaches back to the client mid-request — `ctx.elicit()`, `ctx.elicit_url()`, `ctx.session.create_message()`, `ctx.session.list_roots()`, or any other `ServerSession` request helper — raises `NoBackChannelError` on such a connection instead of sending. An in-process `Client(server)` negotiates 2026-07-28 by default (see [`Client` defaults to `mode='auto'`](#client-defaults-to-modeauto)), so the first smoke test of an unchanged v1 sampling or elicitation tool fails, and setting `sampling_callback=` / `elicitation_callback=` on the client changes nothing because no request ever reaches the client.

`NoBackChannelError` lives in `mcp.shared.exceptions` and subclasses `MCPError` (code `-32600`, message `Cannot send '<method>': this transport context has no back-channel for server-initiated requests.`). Raised inside an `@mcp.tool()` it reaches the client as a top-level JSON-RPC error, not `CallToolResult(is_error=True)` — see [`MCPError` raised from an `@mcp.tool()` handler now surfaces as a JSON-RPC error](#mcperror-raised-from-an-mcptool-handler-now-surfaces-as-a-json-rpc-error) — and the [Troubleshooting](troubleshooting.md) page walks through the client-side traceback. The same exception is raised on a legacy session against a `stateless_http=True` server, and on the request-scoped channel of a stateful legacy session against a `json_response=True` server (a JSON body carries exactly one response, so a mid-request `ctx.elicit()` cannot ride it; the session's standalone `GET` stream still carries unrelated messages) — both places v1 dropped the message and stalled ([`Server.run()` no longer takes a `stateless` flag](#serverrun-no-longer-takes-a-stateless-flag)). Notifications never raise it: `send_log_message()`, `send_tool_list_changed()`, and the other notification helpers are dropped with a debug log where no channel exists (and the change-notification helpers are dropped on every 2026-era connection, channel or not — see [change notifications travel only on `subscriptions/listen` streams](#change-notifications-travel-only-on-subscriptionslisten-streams)), and `UrlElicitationRequiredError` from a tool is unaffected (it is an error response, not a request).

Two ways to migrate:

- **Keep the push behavior for now** by connecting at a pre-2026 version: `Client(server, mode="legacy", sampling_callback=..., elicitation_callback=...)` reproduces v1's `initialize` handshake, in-process included; a lowlevel `ClientSession` you `initialize()` yourself already negotiates a 2025-era version, so hand-rolled test harnesses are unaffected. Sampling and roots stay deprecated on this path ([SEP-2577](#roots-sampling-and-logging-methods-deprecated-sep-2577)).
- **Port to the era-portable form**: return the question instead of pushing it — a `Resolve(...)`-backed parameter whose resolver returns `Elicit`, `Sample`, or `ListRoots` (all in `mcp.server.mcpserver`). The SDK elicits directly on a legacy connection and drives the `InputRequiredResult` multi-round trip at 2026-07-28, with one tool body for both eras; see [Dependencies](handlers/dependencies.md), [Multi-round-trip requests](handlers/multi-round-trip.md), and [Serving legacy clients](run/legacy-clients.md).

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

The client's same `elicitation_callback` answers both; the resolver lets the server *return* the question instead of pushing it.

### Log messages are delivered only to requests that opt in

At 2026-07-28 the deprecated logging capability changes shape: `logging/setLevel` is gone, and log delivery becomes a per-request opt-in. A server MUST NOT send `notifications/message` for a request whose `_meta` lacks `io.modelcontextprotocol/logLevel`, and when the key is present it sends only entries at or above that level, on that request's own stream. So on a 2026-era connection the request-scoped log calls — `ctx.info(...)` and friends on `MCPServer`'s `Context`, `ctx.session.send_log_message(...)`, `Context.log(...)` — are silently dropped (debug-logged) unless the request opted in, and dropped when they fall below the requested level; `Connection.log(...)`, which has no request to opt in, never sends there. Nothing changes on 2025-11-25 and earlier connections.

The most visible consequence is the in-process `Client(server)`, which negotiates 2026-07-28 by default: a `logging_callback` that used to receive every message now receives nothing until the client opts in. `Client` grows a `log_level` argument for exactly this, stamped as the reserved `_meta` key on every modern request:

```python
async with Client(server, logging_callback=on_log, log_level="info") as client:
    await client.call_tool("chatty", {})  # info and above reach `on_log`
```

`log_level=None` (the default) means no opt-in — a `logging_callback` alone is not one — and a single request can override the client-wide default by supplying the key in its own `meta=` (e.g. `meta={LOG_LEVEL_META_KEY: "debug"}` from `mcp_types`). The opt-in is what the spec calls for on 2026-era servers generally, not just this SDK's. Because 2026 log delivery is request-scoped by construction, `related_request_id` on `send_log_message` no longer selects the standalone stream there: whatever is delivered rides the requesting stream.

### Change notifications travel only on `subscriptions/listen` streams

On a 2026-07-28 connection, `notifications/tools/list_changed`, `notifications/prompts/list_changed`, `notifications/resources/list_changed`, and `notifications/resources/updated` reach a client only through a `subscriptions/listen` stream it opened — the spec forbids sending a notification type a subscription did not request. The v1-style session helpers (`ctx.session.send_tool_list_changed()`, `send_prompt_list_changed()`, `send_resource_list_changed()`, `send_resource_updated(uri)`) push a bare copy onto the connection's standalone channel instead, so on such a connection they are dropped with a debug log: silently on streamable HTTP (there is no standalone channel), and on stdio, where earlier v2 releases wrote the bare notification to the shared pipe, it is now dropped too. On pre-2026 connections the helpers behave as in v1.

Migrate to publishing on the subscription bus, which stamps and filters per stream: `await ctx.notify_tools_changed()`, `notify_prompts_changed()`, `notify_resources_changed()`, and `notify_resource_updated(uri)` on `MCPServer`'s `Context`, or `await bus.publish(...)` on a low-level `Server`'s own `SubscriptionBus` — see [Subscriptions](handlers/subscriptions.md). A stream only ever receives the kinds and URIs the server acknowledged for it; to gate per caller which subscriptions may be opened, refuse `subscriptions/listen` in a middleware (`MCPServer(middleware=[...])`), covered on the same page.

### Servers validate `Mcp-Param-*` headers against the request body ([SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243))

On the 2026-07-28 Streamable HTTP path, a `tools/call` whose tool declares `x-mcp-header` annotations is validated before dispatch — each annotated argument and its mirroring `Mcp-Param-*` header must be present together and agree (after base64-sentinel decoding; integers compare numerically), or absent together. A violation is rejected with HTTP 400 and JSON-RPC error `-32020` (`HeaderMismatch`), as the spec requires. A client that sends an annotated argument *without* its header — for example one that never listed the tool — is therefore rejected instead of silently served; the spec's recovery is to re-list and retry. On the client side, `ClientSession.call_tool` emits these headers automatically for annotated arguments of any tool it has listed; list the tool first, and note that pre-2026 connections and non-HTTP transports never emit them.

There is nothing to configure. The server resolves the called tool's schema through its own registered `tools/list` handler (for `MCPServer`, the built-in one), so the validated catalog is exactly what that caller would be shown. Two consequences worth knowing: the listing runs internally on validated calls, so middleware and an expensive or paginated `tools/list` handler see extra invocations; and validation is skipped — never failing the call — when no `tools/list` handler is registered, the tool isn't in the listing, the handler raises (logged as an error), or the call has no arguments and no `Mcp-Param-*` headers. Headers with no matching annotation are ignored; a recognized header supplied more than once is rejected, as is a duplicated `MCP-Protocol-Version`, `Mcp-Method`, or `Mcp-Name` line. The codec and validator are public in `mcp.shared.inbound` (`decode_header_value`, `validate_mcp_param_headers`) for low-level servers hosting their own HTTP entry.

Base64-sentinel decoding is strict everywhere it applies, including the `Mcp-Name` header: a `=?base64?...?=` value whose payload is not canonical base64 (wrong padding, stray characters, non-zero trailing bits) or not valid UTF-8 is rejected as malformed rather than leniently decoded.

## Need Help?

If you encounter issues during migration:

1. Check the [API Reference](api/mcp/index.md) for updated method signatures
2. Review the [examples](https://github.com/modelcontextprotocol/python-sdk/tree/main/examples) for updated usage patterns
3. Open an issue on [GitHub](https://github.com/modelcontextprotocol/python-sdk/issues) if you find a bug or need further assistance
