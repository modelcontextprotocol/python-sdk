# Migration Guide: v1 to v2

This guide covers the breaking changes introduced in v2 of the MCP Python SDK and how to update your code.

## Overview

Version 2 of the MCP Python SDK introduces several breaking changes to improve the API, align with the MCP specification, and provide better type safety.

## Breaking Changes

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
[Multi-round-trip requests](advanced/multi-round-trip.md)). If you call these
methods directly, narrow with `isinstance` (or
`assert not isinstance(result, InputRequiredResult)` when your prompt and
resource functions never return one). `Prompt.render()` and
`ResourceTemplate.create_resource()` carry the same union.

`ctx.read_resource()` inside a handler is unchanged: it still returns content,
and raises `RuntimeError` if the resource requests input. A handler that wants
to receive the `InputRequiredResult` and forward it as its own result calls
`MCPServer.read_resource(uri, context)` directly — but not from a tool whose
dependencies elicit via `Resolve(...)`: the resolver owns that tool's
`request_state` channel, and a forwarded result's state would clobber it.

### `MCPError` raised from an `@mcp.tool()` handler now surfaces as a JSON-RPC error

Raising `MCPError` (or a subclass such as `UrlElicitationRequiredError`) inside
an `@mcp.tool()` handler now produces a top-level JSON-RPC error response with
the raised `code`, `message`, and `data` intact. Previously the tool wrapper
caught it like any other exception and returned `CallToolResult(isError=True)`,
which discarded the error code and structured `data`.

`MCPError` carries `ErrorData` and is the SDK's protocol-error type — raise it
when the request itself should be rejected (missing client capability,
elicitation required, invalid parameters). For tool *execution* failures the
calling LLM should see and react to, raise any other exception or return
`CallToolResult(is_error=True, ...)` directly; that path is unchanged.

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

### `StreamableHTTPTransport.protocol_version` attribute removed

The transport no longer holds per-connection protocol state; era-dependent headers (e.g. `MCP-Protocol-Version`) are now supplied per-message by the session. If you were reading `transport.protocol_version` to learn the negotiated version, read `session.protocol_version` (or `client.protocol_version` on the high-level `Client`) instead.

The `MCP_PROTOCOL_VERSION` header-name constant has moved: import `MCP_PROTOCOL_VERSION_HEADER` from `mcp.shared.inbound` instead of `MCP_PROTOCOL_VERSION` from `mcp.client.streamable_http`.

### `terminate_windows_process` removed

The deprecated `mcp.os.win32.utilities.terminate_windows_process` function has been
removed. Process termination is handled internally by the `stdio_client` context
manager; there is no replacement API. The Windows tree-termination helper
`terminate_windows_process_tree` no longer accepts a `timeout_seconds` argument —
the value was never used (Job Object termination is immediate).

### `stdio_client` no longer kills children of a gracefully-exited server on POSIX

When a server exits on its own after `stdio_client` closes its stdin, background
child processes the server leaves behind are no longer killed on POSIX — their
lifetime is the server's business. The old behavior was a side effect of a shutdown
wait gated on the stdio pipes closing rather than on process exit: a child holding
an inherited pipe made a well-behaved server look hung, so its whole process tree
was killed. (That gating is an asyncio behavior specific to Python 3.11+ — on
Python 3.10 and the trio backend the old wait already resolved on process exit, so
the spurious kill never fired there.) A server that does not exit within the grace
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
side instead of leaving requests waiting indefinitely.

`terminate_posix_process_tree` now requires the process to lead its own process
group (spawned with `start_new_session=True`); the `getpgid()` lookup and the
per-process terminate/kill fallback are gone. The win32 utilities logger is now
named `mcp.os.win32.utilities` (was `client.stdio.win32`).

### WebSocket transport removed

The WebSocket transport has been removed: `mcp.client.websocket.websocket_client`, `mcp.server.websocket.websocket_server`, and the `ws` optional dependency extra (`mcp[ws]`) no longer exist. WebSocket was never part of the MCP specification. Use the streamable HTTP transport instead (`mcp.client.streamable_http.streamable_http_client` on the client, `streamable_http_app()` on the server), which supports bidirectional communication with server-to-client streaming over standard HTTP.

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

The following deprecated type aliases and classes have been removed from `mcp_types`:

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
from mcp_types import ContentBlock, ResourceTemplateReference
# Use `str` instead of `Cursor` for pagination cursors
```

### Field names changed from camelCase to snake_case

All Pydantic model fields in `mcp_types` now use snake_case names for Python attribute access. The JSON wire format is unchanged — serialization still uses camelCase via Pydantic aliases.

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

### Server handler results are validated against the protocol schema

Results returned from server handlers are now validated against the negotiated protocol version's schema before being sent. A result that does not conform raises on the server side and the client receives an `INTERNAL_ERROR` response. The case most existing code will hit is `Tool.inputSchema`: the spec requires it to contain `"type": "object"`, so an empty `{}` is now rejected.

### Client validates inbound traffic against the protocol schema

`ClientSession` now validates server requests, notifications, and results against the negotiated protocol version's schema before parsing them into `mcp_types` models. Spec-invalid server output that the previous monolith parse tolerated may now raise `pydantic.ValidationError` from `list_tools()`, `call_tool()`, and similar calls. `_meta` remains the sanctioned place for result extras (and `experimental` for capability extras).

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
from mcp_types import PaginatedRequestParams

result = await session.list_resources(params=PaginatedRequestParams(cursor="next_page_token"))
result = await session.list_tools(params=PaginatedRequestParams(cursor="next_page_token"))
```

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

### `Client` defaults to `mode='auto'`

In v1, connecting to a server always performed the `initialize` handshake. In v2, `Client` defaults to `mode='auto'`: on enter it probes `server/discover` and, if the server doesn't support it, falls back to the `initialize` handshake. Pass `mode='legacy'` to force the initialize handshake and reproduce v1's byte-identical pre-2026 behavior, or pass a modern protocol-version string (e.g. `mode='2026-07-28'`) to pin a version without probing.

For an in-process `Client(server)` (where `server` is a `Server` or `MCPServer` instance), `mode='auto'` dispatches calls directly through `DirectDispatcher` with no JSON-RPC framing. Pass `mode='legacy'` if you need the in-memory JSON-RPC transport that v1 used.

`Client.send_ping()` is deprecated (ping is removed in 2026-07-28); pin `mode='legacy'` if you need it.

### `InputRequiredResult` handling differs between `Client` and `ClientSession`

For protocol 2026-07-28, `tools/call`, `prompts/get`, and `resources/read` may return an `InputRequiredResult` asking the client to supply additional input (sampling, elicitation, roots) and retry.

On the high-level `Client`, `call_tool`, `get_prompt`, and `read_resource` resolve this automatically: they dispatch each requested input to the matching callback (`sampling_callback`, `elicitation_callback`, `list_roots_callback`) and retry until a final result is returned, so the call still returns the bare `CallToolResult` / `GetPromptResult` / `ReadResourceResult`. The round limit is `Client(input_required_max_rounds=...)` (default 10). Earlier v2 prereleases exposed an `allow_input_required` parameter on these `Client` methods; that parameter has been removed. For manual control use `client.session.call_tool(..., allow_input_required=True)`. Note that `read_timeout_seconds` now bounds each underlying round, not the whole loop; wrap the call in `anyio.fail_after(...)` for a whole-loop bound.

On `ClientSession`, `call_tool` / `get_prompt` / `read_resource` still return the bare result and raise `RuntimeError` if the server requests input. Pass `allow_input_required=True` to receive the `InputRequiredResult` instead, then drive the loop yourself with `input_responses=` / `request_state=`. `ClientSessionGroup.call_tool` accepts the same flag.

### `call_tool` mirrors `x-mcp-header` arguments into `Mcp-Param-*` headers ([SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243))

For protocol 2026-07-28 over Streamable HTTP, a tool's input-schema property may carry an `x-mcp-header` annotation. When a tool the client has listed is called, each annotated argument is mirrored into an `Mcp-Param-<name>` request header (string verbatim, integer as decimal, boolean as `true`/`false`, base64-sentinel-wrapped when not header-safe; `null`/absent arguments are omitted). The argument is also left in the request body. `list_tools` caches a tool's annotations, so list a tool before calling it to enable mirroring; a tool the client never listed emits no `Mcp-Param-*` headers. Other transports ignore the annotation.

### `Client` verbs may serve cached responses ([SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549))

On protocol 2026-07-28, servers attach caching hints (`ttlMs`, `cacheScope`) to the cacheable results, and `Client` now honors them: `list_tools`, `list_prompts`, `list_resources`, `list_resource_templates`, and `read_resource` may serve a cached response instead of making a round trip, for as long as the server's `ttlMs` says the result is fresh. Servers that send no hints — including every pre-2026 server — see identical call-for-call behavior, because hint-less results are not cached. Pass `Client(..., cache=False)` to disable the cache and restore v1 behavior exactly; per-call control (`cache_mode`) and configuration (`CacheConfig`) are described in [Caching hints](advanced/caching.md).

### Server extensions API ([SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133))

`MCPServer` now accepts opt-in extensions that bundle MCP behaviour behind a
reverse-DNS identifier and advertise it under `ServerCapabilities.extensions`
(the 2026-07-28 capability map). An extension subclasses `mcp.server.extension.Extension`
and overrides only the contribution methods it needs: `tools()`/`resources()`/`methods()`
(additive) and `intercept_tool_call()` (wraps `tools/call`). The `identifier` must be a
`vendor-prefix/name` string following the spec's `_meta` key grammar; a class-level
`identifier` is validated when the subclass is defined, one assigned in `__init__` when
the extension is registered. Pass instances at construction:

```python
from mcp.server.mcpserver import MCPServer
from mcp.server.apps import Apps

mcp = MCPServer("demo", extensions=[Apps()])
```

The reference extension is `mcp.server.apps.Apps` (`io.modelcontextprotocol/ui`):
it binds a tool to a `ui://` UI resource via `_meta.ui.resourceUri`, and
`client_supports_apps(ctx)` gates the SEP-2133 text-only fallback — `True` only
when the client's ui-extension settings list the `text/html;profile=mcp-app`
MIME type, per the Apps spec's required `mimeTypes` field. Every
`@apps.tool(resource_uri=...)` must have a matching resource registered on the
same `Apps` instance (`add_html_resource` for inline HTML, `add_resource` for a
pre-built `Resource`); a tool bound to an unregistered URI raises at
`MCPServer(...)` construction rather than 404ing on `resources/read` at runtime.

Extension methods are strictly additive: a `MethodBinding` cannot name a
spec-defined request method, and registering one whose method collides with
another handler raises at construction. A `MethodBinding` may set
`protocol_versions` to scope an extension method to specific wire versions
(`frozenset()` is rejected — use `None` to admit every version); a request at
any other version is `METHOD_NOT_FOUND`. An
extension handler can call `mcp.server.mcpserver.require_client_extension(ctx, identifier)`
to reject a request with the `-32021` (missing required client capability) error
when the client did not declare the extension.

Clients advertise extension support with the new `Client(extensions=...)` /
`ClientSession(extensions=...)` argument, mirrored into `ClientCapabilities.extensions`.
The extensions capability map is negotiated over `server/discover` (modern path);
a legacy `initialize` handshake does not carry it. Extensions are off by default
and never alter behaviour unless registered.

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

### Streamable HTTP: lifespan now entered once at manager startup

When serving streamable HTTP (stateful or `stateless_http=True`), the server's `lifespan` context manager is now entered once when `StreamableHTTPSessionManager.run()` starts, and the resulting state is shared across all sessions and requests. Previously each session (stateful) or each request (stateless) entered and exited `lifespan` independently.

Lifespans that set up process-wide state (connection pools, caches, background tasks) are unaffected — they now run once instead of per session/request. If your lifespan was acquiring per-connection resources, move that acquisition into the handler body; per-connection cleanup belongs on the connection's `exit_stack` (the public surface for reaching it from high-level `@mcp.tool()` handlers is being finalised as part of the public-surface review).

### `Server.run()` no longer takes a `stateless` flag; `StatelessModeNotSupported` removed

The `stateless: bool` parameter on the lowlevel `Server.run()` has been removed. Stateless serving is now a property of how the connection is constructed (the streamable-HTTP manager builds a born-ready `Connection` per request), not a flag the loop driver inspects.

`StatelessModeNotSupported` has been removed. Server-initiated requests that have no channel to travel on now raise `NoBackChannelError` (an `MCPError` subclass) — the same exception regardless of why the channel is absent. If you were catching `StatelessModeNotSupported`, catch `NoBackChannelError` instead.

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

See [URI templates](advanced/uri-templates.md) for the full template syntax,
security configuration, and filesystem safety utilities.

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

### `MCPServer`'s `Context` logging: `message` renamed to `data`, `extra` removed

On the high-level `Context` object (`mcp.server.mcpserver.Context`), `log()`, `.debug()`, `.info()`, `.warning()`, and `.error()` now take `data: Any` instead of `message: str`, matching the MCP spec's `LoggingMessageNotificationParams.data` field which allows any JSON-serializable value. The `extra` parameter has been removed — pass structured data directly as `data`.

The lowlevel `ServerSession.send_log_message(data: Any)` already accepted arbitrary data and is unchanged.

`Context.log()` also now accepts all eight [RFC-5424](https://datatracker.ietf.org/doc/html/rfc5424) log levels (`debug`, `info`, `notice`, `warning`, `error`, `critical`, `alert`, `emergency`) via the `LoggingLevel` type, not just the four it previously allowed.

```python
# Before
await ctx.info("Connection failed", extra={"host": "localhost", "port": 5432})
await ctx.log(level="info", message="hello")

# After
await ctx.info({"message": "Connection failed", "host": "localhost", "port": 5432})
await ctx.log(level="info", data="hello")
```

Positional calls (`await ctx.info("hello")`) are unaffected.

### `Context.elicit()` schema gate validates the rendered schema

`Context.elicit()` (and `elicit_with_validation()`) now render the schema first and validate each property against the spec's `PrimitiveSchemaDefinition`, raising `TypeError` at the call site for anything outside it. `Optional[T]` fields render as `{"type": ...}` with the field omitted from `required` (previously the non-spec `anyOf` shape). A bare `list[str]` field is rejected because it renders without the required enum items; use `list[Literal[...]]` or `list[str]` with `json_schema_extra` supplying the items. Unions of multiple primitives (e.g. `int | str`) and nested models are rejected.

A schema-mismatched *accepted* answer also fails differently: the call now raises `ValueError` with a stable message ("Received an accepted elicitation whose content does not match the requested schema") instead of letting pydantic's `ValidationError` escape with its internals. Code that caught `ValidationError` around `ctx.elicit()` should catch `ValueError` (or rely on the tool's error result).

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

`ServerRequestContext` is now a standalone dataclass — it no longer subclasses `RequestContext[ServerSession]`. It carries the same fields (`session`, `request_id`, `meta`, `lifespan_context`, `request`, `close_sse_stream`, `close_standalone_sse_stream`) plus new `protocol_version: str`, `method: str`, and raw `params: Mapping[str, Any] | None` fields (the last two let middleware read and rewrite the inbound message), so handler code is unaffected, but `isinstance(ctx, RequestContext)` checks and `RequestContext[ServerSession]` annotations need updating to `ServerRequestContext`.

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

### Version constants

`SUPPORTED_PROTOCOL_VERSIONS` is deprecated — it's now the union of `HANDSHAKE_PROTOCOL_VERSIONS` (initialize-handshake versions) and `MODERN_PROTOCOL_VERSIONS` (per-request-envelope versions). If you were using it to mean "versions the initialize handshake accepts", switch to `HANDSHAKE_PROTOCOL_VERSIONS`. Named scalars derived from these tuples are now exported alongside them — `LATEST_HANDSHAKE_VERSION`, `LATEST_MODERN_VERSION`, `OLDEST_SUPPORTED_VERSION` — so prefer those over indexing the tuples directly. All of these live in `mcp_types.version` (previously `mcp.shared.version`): `from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS`.

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

### Handler progress reporting: prefer `ctx.report_progress()` over manual `progress_token`

Reading `ctx.meta["progress_token"]` and calling `session.send_progress_notification(token, ...)` is specific to the JSON-RPC transport path. On the in-process modern path (`DirectDispatcher` / `Client(server)`), there is no wire token in `_meta`, so handlers that gate progress on the token's presence go silent.

`ctx.report_progress(progress, total, message)` works on every dispatcher: it sends a progress notification when a token is present and routes the update through the dispatcher's progress channel otherwise, no-opping only when the caller did not request progress at all. `session.send_progress_notification(progress_token, ...)` is unchanged and still works on JSON-RPC transports for code that already holds a token.

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

`Client` accepts the same callback parameters the old helper did (`sampling_callback`, `list_roots_callback`, `logging_callback`, `message_handler`, `elicitation_callback`, `client_info`) plus `raise_exceptions` to surface server-side errors and `mode` to control version negotiation (`'auto'` by default; `'legacy'` reproduces v1's initialize-only handshake).

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

### Lowlevel `Server`: `add_request_handler` is now public and takes `params_type`

The private `_add_request_handler(method, handler)` escape hatch is now the public `add_request_handler(method, params_type, handler)`, alongside a matching `add_notification_handler`. Each takes a `params_type` model that incoming params are validated against before the handler runs. A message with no `params` member validates `{}` against the model, so handlers never receive `None`: all-optional models arrive with their defaults, and models with required fields reject the message as `INVALID_PARAMS` before the handler runs (matching the Go SDK).

```python
# Before (v1 / earlier v2 prereleases)
server._add_request_handler("custom/method", my_handler)

# After (v2)
server.add_request_handler("custom/method", MyParams, my_handler)
server.add_notification_handler("notifications/custom", MyNotifyParams, my_notify_handler)
```

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
from mcp_types import CallToolRequestParams, CallToolResult, TextContent


async def handle_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    await ctx.session.send_log_message(level="info", data="Processing...")
    return CallToolResult(
        content=[TextContent(type="text", text="Done")],
        is_error=False,
    )
```

### `ServerRequestContext`: request-specific fields are now optional

`ServerRequestContext` now uses optional fields for request-specific data (`request_id`, `meta`, etc.) so it can be used for both request and notification handlers. In notification handlers, these fields are `None`.

```python
from mcp.server import ServerRequestContext

# request_id, meta, etc. are available in request handlers
# but None in notification handlers
```

### `ServerSession` is now a thin proxy (no longer a `BaseSession`)

`ServerSession` no longer subclasses `BaseSession`. It is now a small connection-scoped proxy that exposes `send_request`, `send_notification`, the typed convenience helpers (`create_message`, `elicit_form`, `send_log_message`, `send_tool_list_changed`, ...), `client_params`, `protocol_version`, and `check_client_capability`. The receive loop, `initialize` handling, and per-request task isolation that previously lived in `ServerSession` have moved to `JSONRPCDispatcher` and `ServerRunner`.

`ServerSession` is normally constructed for you by `Server.run()` and reached via `ctx.session` in handlers, so most servers are unaffected. If you were constructing or subclassing it directly:

**Constructor change:**

```python
# Before (v1)
session = ServerSession(read_stream, write_stream, init_options, stateless=False)

# After (v2)
session = ServerSession(request_outbound, connection)
# where `request_outbound` is an Outbound and `connection` is a Connection
```

In practice, replace direct `ServerSession` use with `Server.run(read_stream, write_stream, init_options)` and let the framework wire it up.

**Removed from `mcp.server.session`:**

- `InitializationState` enum and `ServerSession._initialization_state` — initialization tracking is now on `Connection` (`connection.initialized` is an `anyio.Event`, `connection.client_params` holds the init params).
- `ServerRequestResponder` type alias.
- `ServerSession.incoming_messages` stream — there is no longer a public stream of inbound messages to iterate. Register handlers via the `on_*` constructor params (or `add_request_handler`) and use `Server.middleware` to observe every inbound request and notification (`initialize`, unknown methods, validation failures, and `notifications/initialized` included).
- `ServerSession.__aenter__` / `__aexit__` — `ServerSession` is no longer an async context manager.
- The private `_receive_loop`, `_received_request`, `_received_notification`, and `_handle_incoming` overrides — there is nothing to override on `ServerSession` anymore. To intercept inbound messages, use `Server.middleware` (see the `_handle_*` removal section above).

### `BaseSession` / `RequestResponder`: server-side cancellation tracking removed

`BaseSession._in_flight` and the `RequestResponder` members that supported it (`cancel()`, the `cancelled` and `in_flight` properties, the `on_complete` constructor argument, and the internal `CancelScope`) have been removed. These existed to let `ServerSession` cancel a handler when a `CancelledNotification` arrived; `ServerSession` no longer drives a receive loop, so they were dead code. Inbound-cancellation handling for the server now lives in `JSONRPCDispatcher`.

`BaseSession` itself has since been removed entirely; see the next section.

### `ClientSession` now runs on `JSONRPCDispatcher`; `BaseSession` removed

`ClientSession`'s public surface is unchanged — same constructor, typed methods, manual `initialize()`, and async context-manager lifecycle — but `BaseSession`, the v1 receive loop underneath it, is removed with no shim. The engine now lives in `JSONRPCDispatcher` (`mcp.shared.jsonrpc_dispatcher`). To customize client behavior, use the `ClientSession` constructor callbacks, or pass a pre-built dispatcher via the new keyword-only `dispatcher=` constructor argument (e.g. a `DirectDispatcher` for in-process embedding).

Behavior changes:

- **Callbacks and notifications now run concurrently.** In v1 the receive loop processed one inbound message at a time, so callbacks ran inline and in order. Now each delivery starts in arrival order but runs as its own task. Server-initiated request callbacks (`sampling`, `elicitation`, `roots`) no longer block other traffic, may themselves send requests without deadlocking, and are interrupted if the server sends `notifications/cancelled` (the request is then answered with an error). Notification callbacks (`logging_callback`, `progress_callback`, `message_handler`) may interleave, and a `progress_callback` may run after the request it reports on has returned; there is no built-in bound on concurrent deliveries. Transport-level errors reach `message_handler` the same way, and a `message_handler` that raises is logged rather than fatal to the session. Callbacks that need strict sequencing must coordinate themselves.
- **Timeouts**: a timed-out or abandoned request is now followed by `notifications/cancelled`, so the server stops the handler instead of leaving it running.
- **A raising request callback** is answered with `code=0` and the exception text; v1 flattened every callback exception to `INVALID_PARAMS`. For a specific error response, return `ErrorData` (unchanged) or raise `MCPError`. One carve-out: pydantic's `ValidationError` is still answered with `INVALID_PARAMS`, as in v1.
- **`send_request` before entering the context manager** raises `RuntimeError` immediately; v1 wrote to the transport and hung until the timeout. After the connection has closed it raises `MCPError` (`CONNECTION_CLOSED`) instead. `send_notification` before entry still works.
- **`send_notification` no longer takes `related_request_id`, and `send_request` no longer accepts `ServerMessageMetadata`.** No client transport ever serialized these hints; progress and response correlation via `progressToken` and the request id is unaffected.
- **Client callbacks now receive `mcp.client.ClientRequestContext`** (its `request_id` is always populated); the private `mcp.shared._context.RequestContext` generic is deleted. Annotations spelled `RequestContext[ClientSession]` become `ClientRequestContext`.

`mcp.shared.session` is now a compatibility module: `ProgressFnT` is re-exported (its home is `mcp.shared.dispatcher`), and `RequestResponder` remains as a typing-only stub so `MessageHandlerFnT` annotations keep importing. `RequestResponder.respond()` no longer exists.

### Experimental Tasks support removed

Tasks ([SEP-1686](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1686)) have been removed from the MCP specification and are no longer part of this SDK. The `mcp.client.experimental`, `mcp.server.experimental`, `mcp.shared.experimental`, and `mcp.server.lowlevel.experimental` modules have been removed, along with the `experimental` properties on `ClientSession`, `ServerSession`, `Server`, and `ServerRequestContext`. The corresponding `Task*` types remain in `mcp_types` as types-only definitions.

Tasks are expected to return as a separate MCP extension in a future release.

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

The 2026-07-28 spec restricts `notifications/progress` to the server-to-client direction only — `ProgressNotification` is no longer in `ClientNotification`. `Client.send_progress_notification()` and `ClientSession.send_progress_notification()` now carry `typing_extensions.deprecated` and emit `mcp.MCPDeprecationWarning` at runtime. They continue to work against servers negotiating 2025-11-25 or earlier.

On the server side, prefer the new dispatcher-agnostic `ServerSession.report_progress(progress, total, message)` (and `Context.report_progress()` on `MCPServer`) over the raw `ServerSession.send_progress_notification(progress_token, …)`. `report_progress` encapsulates the "no-op when the caller did not request progress" rule and works on every dispatcher; the raw token-taking form remains for handlers that read `_meta.progressToken` directly.

## Bug Fixes

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

### Lowlevel `Server`: `subscribe` capability now correctly reported

Previously, the lowlevel `Server` hardcoded `subscribe=False` in resource capabilities even when a `subscribe_resource()` handler was registered. The `subscribe` capability is now dynamically set to `True` when an `on_subscribe_resource` handler is provided. Clients that previously didn't see `subscribe: true` in capabilities will now see it when a handler is registered, which may change client behavior.

### Unknown request methods now return `-32601` (Method not found)

In v1, a request for a method the SDK didn't recognize failed request-union validation and was answered with `-32602` (`"Invalid request parameters"`, empty `data`). Any method the receiver doesn't serve — unrecognized, or a spec method with no registered handler — is now answered with the JSON-RPC-specified `-32601` (`"Method not found"`), with the method name in `data`, on both the server and the client side, in every initialization state. Update anything that matched on the old code for this case.

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

## New Features

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

### Identity Assertion Authorization Grant for enterprise IdP flows (SEP-990)

The SDK now supports [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990)'s enterprise identity-provider policy controls. The client presents an Identity Assertion Authorization Grant (ID-JAG) - a signed JWT issued by the enterprise IdP - to the MCP authorization server using the [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) jwt-bearer grant (`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`, the ID-JAG as `assertion`), and receives an MCP access token. This matches the SEP-990 normative profile and interoperates with the other MCP SDKs. (Leg 1 - exchanging the user's IdP ID token for the ID-JAG against the IdP - is deployment-specific and out of scope for the SDK.) This is additive and opt-in on both sides; existing flows are unchanged.

On the client, `IdentityAssertionOAuthProvider` (in `mcp.client.auth.extensions.identity_assertion`) is an `httpx.Auth` that posts the jwt-bearer request. The ID-JAG is supplied lazily through an async `assertion_provider(audience, resource)` callback - `audience` is the authorization server's issuer (the ID-JAG `aud`) and `resource` is the MCP server's identifier (the ID-JAG `resource` claim):

```python
from mcp.client.auth.extensions.identity_assertion import IdentityAssertionOAuthProvider


async def fetch_id_jag(audience: str, resource: str) -> str:
    # The ID-JAG must carry `audience` as `aud` and `resource` as its `resource` claim.
    return await my_idp.issue_id_jag(audience=audience, resource=resource)


provider = IdentityAssertionOAuthProvider(
    server_url="https://mcp.example.com/mcp",
    storage=my_token_storage,
    client_id="enterprise-mcp-client",
    client_secret="enterprise-mcp-secret",
    issuer="https://auth.example.com",
    assertion_provider=fetch_id_jag,
)
```

SEP-990 §5.1 requires the client to authenticate; this SDK currently requires a shared secret, so `client_secret` is mandatory (`token_endpoint_auth_method` chooses `client_secret_post` (default) or `client_secret_basic`; the spec also permits `private_key_jwt`). The authorization server is configuration, not discovery: `issuer` is the AS the client is provisioned for, authorization-server metadata is fetched from that issuer's [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) well-known, and the resource server is never asked which AS to use - so a hostile resource server cannot redirect the ID-JAG or secret.

On the authorization server, set `AuthSettings(identity_assertion_enabled=True)` (or pass `identity_assertion_enabled=True` to `create_auth_routes`) and implement `exchange_identity_assertion` on your `OAuthAuthorizationServerProvider`. The method receives an `IdentityAssertionParams` (the ID-JAG `assertion`, requested scopes, and request `resource`) and returns a plain [RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749) `OAuthToken`. The flag gates both metadata advertisement and the token endpoint: when off, `/token` rejects the grant with `unsupported_grant_type` even if the provider implements the hook. When on, the metadata advertises the jwt-bearer grant and the `urn:ietf:params:oauth:grant-profile:id-jag` profile in `authorization_grant_profiles_supported` (the discovery mechanism per ext-auth §6).

The implementation is responsible for validating the assertion per RFC 7523 §3 and SEP-990 §5.1 - verify the signature/`iss`/`exp`/`typ`, require `aud` to be this AS, require the ID-JAG's `client_id` claim to match the authenticated client, audience-restrict the issued token to the ID-JAG's `resource` claim (not the client-controlled request `resource`), and derive scopes from the ID-JAG rather than granting the request verbatim. See `examples/snippets/servers/identity_assertion_server.py`, which fails closed. Two hardening points are enforced by the SDK: the handler rejects clients without a stored secret before calling the hook (and `ClientAuthenticator` itself now refuses a secret-based auth method registered without a secret), and Dynamic Client Registration refuses the jwt-bearer grant so the ID-JAG flow requires a pre-registered confidential client.

### 2025-11-25 and 2026-07-28 protocol fields modeled

`mcp_types` models the 2025-11-25 and 2026-07-28 protocol fields (e.g. `resultType`, `ttlMs`/`cacheScope` on cacheable results, `inputResponses`/`requestState` on retried requests), so inbound payloads carrying these keys parse into typed fields and round-trip. `ttlMs`/`cacheScope` default to `0`/`"private"` (immediately stale, not shared-cacheable); `resultType` defaults to `"complete"` on concrete results (`None` on `EmptyResult`); the server strips all of them from the wire at pre-2026 versions. Servers set per-method values with `cache_hints={method: CacheHint(...)}` on the `Server`/`MCPServer` constructor — see [Caching hints](advanced/caching.md).

### `streamable_http_app()` available on lowlevel Server

The `streamable_http_app()` method is now available directly on the lowlevel `Server` class, not just `MCPServer`. This allows using the streamable HTTP transport without the MCPServer wrapper.

```python
from mcp.server import Server, ServerRequestContext
from mcp_types import ListToolsResult, PaginatedRequestParams


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

### `ElicitationResult` is now a subscriptable generic alias

`ElicitationResult` is now a `TypeAliasType` instead of a plain union, so `ElicitationResult[Confirm]` works as an annotation (resolver dependency injection consumes it that way - see [Dependencies](tutorial/dependencies.md)). The members are unchanged: `AcceptedElicitation[T] | DeclinedElicitation | CancelledElicitation`.

The one behavioral change: a runtime `isinstance(result, ElicitationResult)` now raises `TypeError`. Check against the member classes directly instead:

```python
result = await ctx.elicit("Proceed?", Confirm)
if isinstance(result, AcceptedElicitation):
    ...  # result.data is a Confirm
```

Narrowing on `result.action` (`"accept"` / `"decline"` / `"cancel"`) is unaffected.

## Need Help?

If you encounter issues during migration:

1. Check the [API Reference](api/mcp/index.md) for updated method signatures
2. Review the [examples](https://github.com/modelcontextprotocol/python-sdk/tree/main/examples) for updated usage patterns
3. Open an issue on [GitHub](https://github.com/modelcontextprotocol/python-sdk/issues) if you find a bug or need further assistance
