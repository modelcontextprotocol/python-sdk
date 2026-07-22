# What's new in v2

Two things happened at once in v2. The **SDK was rebuilt**: a new engine under both the client and the server, a first-class `Client`, and a set of renames that a v1 codebase meets on its first import. And the **protocol moved**: v2 speaks the 2026-07-28 revision of MCP, which removes the connection handshake, the session, and every server-initiated request, without stranding the clients you already have.

This page is the tour of both halves, one section per headline, each ending in the page that owns the topic. It is not the porting manual. That is the **[Migration Guide](migration.md)**: every breaking change, with before and after code.

!!! note "v2 is a beta"
    `pip install mcp` still installs v1.x: you opt into v2 with an exact version pin, and the
    API can still move before the stable release, which lands alongside the spec release.
    **[Installation](get-started/installation.md)** has the copy-paste install line and the
    pinning rules. And if anything in v2 breaks, surprises, or slows you down,
    [tell us](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml):
    while v2 is in beta, that is the most useful thing you can send us.

## The SDK: v1 to v2

### `FastMCP` is now `MCPServer`

The high-level server class was renamed, and its module with it. This is the first thing every v1 server hits, because the old import path is gone rather than deprecated:

```python
from mcp.server import MCPServer  # v1: from mcp.server.fastmcp import FastMCP

mcp = MCPServer("Demo")  # v1: FastMCP("Demo")
```

It is also, for a decorator-built server, most of the port. `@mcp.tool()`, `@mcp.resource()`, and `@mcp.prompt()` accept what they accepted in v1 (`@mcp.resource()` adds one optional `security=` keyword), and the input schema still comes from your type hints. Around the edges: everything under `mcp.server.fastmcp.*` now lives under `mcp.server.mcpserver.*`, `ctx.fastmcp` is `ctx.mcp_server`, `get_context()` is gone (declare a `ctx: Context` parameter instead), and the exception base `FastMCPError` is `MCPServerError`. The **[Migration Guide](migration.md#fastmcp-renamed-to-mcpserver)** has the import table.

### `Resolve`: the new way to ask the user for input

Not everything a tool needs should come from the model. New in v2, a tool parameter annotated with `Resolve(fn)` is filled by a function you write instead, invisibly to the model, and that function can return `Elicit(...)` to put a question in front of the user. This is the preferred way to get anything from the client mid-call: the SDK carries the question over whichever mechanism the connection supports (a live elicitation request for a legacy client, a multi-round-trip on 2026-07-28), so one tool body serves both eras. **[Dependencies](handlers/dependencies.md)** is the page.

!!! note
    The other two forms remain when you need them: `ctx.elicit()` still works for clients on
    legacy connections (**[Elicitation](handlers/elicitation.md)**), and a handler can return an
    `InputRequiredResult` itself and drive the rounds by hand, which is also how sampling and
    roots requests travel at 2026-07-28 (**[Multi-round-trip requests](handlers/multi-round-trip.md)**).

### A first-class `Client`

v1 handed you three nested layers: a transport context manager yielding raw streams, a `ClientSession` wrapped around them, and a hand-called `await session.initialize()`. v2 has one object:

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

`Client` takes a server object (in memory, no transport: the testing story), a URL (Streamable HTTP), or any transport context manager such as `stdio_client(...)`. Entering `async with` connects and negotiates the protocol version, whichever era the server speaks; `client.server_capabilities` and `client.protocol_version` are simply there afterwards, and `client.server_info` is too when the server identifies itself (it is `Implementation | None` now, since 2026-era identity is optional). The sampling and elicitation callbacks you registered in v1 still work (their bodies see the same snake_case attribute rename as everything else on this page), they now also answer the 2026-style requests-inside-results (below), and they run concurrently instead of one at a time. `ClientSession` is still underneath for anyone who wants the low-level surface, and `client.session` hands it to you; it moved too (it runs on the new dispatcher engine, and some of its own signatures changed), so read the **[Migration Guide](migration.md#clientsession-now-runs-on-jsonrpcdispatcher-basesession-removed)** before you drop down.

**[The Client](client/index.md)** introduces it, **[Client transports](client/transports.md)** covers the three connection forms, **[Client callbacks](client/callbacks.md)** covers the callbacks themselves, and **[Testing](get-started/testing.md)** shows the in-memory pattern that replaces v1's `create_connected_server_and_client_session()` helper.

### The low-level `Server` was rebuilt, not renamed

If you work at the JSON-RPC layer, this is the "everything is different" part of v2. Here is the same one-tool server both ways; click the markers for what moved.

<!-- The v1 fence cannot be a tested docs_src file (nothing in CI can import the
1.x SDK). Its ground truth: this exact code was run verbatim against a real
mcp==1.28.1 install. If you edit it, re-validate it against 1.x. -->

```python title="v1"
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server

server = Server("Bookshop")


@server.list_tools()  # (1)!
async def list_tools() -> list[types.Tool]:
    return [  # (2)!
        types.Tool(
            name="search_books",
            description="Search the catalog by title or author.",
            inputSchema={  # (3)!
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:  # (4)!
    if name != "search_books":
        raise ValueError(f"Unknown tool: {name}")  # (5)!
    ctx = server.request_context  # (6)!
    return [types.TextContent(type="text", text=f"Found 3 books matching {arguments['query']!r}.")]  # (7)!
```

1. Handlers are registered with decorators (called, with parentheses), any time after the server exists.
2. You return a bare `list[Tool]` and the SDK wraps it into a `ListToolsResult`.
3. Fields are camelCase in Python, and the schema is **enforced**: the SDK jsonschema-validates `call_tool` arguments against it before your function runs, which is why `arguments["query"]` below is safe.
4. One `call_tool` handler serves every tool, and it receives the tool name and the already-validated arguments, unpacked and never `None`.
5. Raising is how a v1 tool signals failure: any exception is caught and returned as `CallToolResult(isError=True)` with `str(e)` as its text, so the calling model reads this message and can retry.
6. The context comes from an ambient ContextVar, reached through the server object mid-request.
7. Bare content blocks are wrapped into a `CallToolResult` for you.

```python title="v2"
--8<-- "docs_src/whats_new/tutorial001.py"
```

1. Fields are snake_case now, and the schema is **advertised but never applied**: nothing checks the arguments before your handler runs.
2. Every handler has the same shape: `async (ctx, params) -> result`. The context is the first argument (`ctx.session`, `ctx.request_id`, `ctx.protocol_version` live on it); this is where `server.request_context` went.
3. You build the full `ListToolsResult` yourself. Returning a bare list is a server-side `TypeError` now, not something the SDK wraps.
4. Typed params in (`params.name`, `params.arguments`), a full result out. Nothing is unpacked, wrapped, or converted for you.
5. Same check, different verb. A `ValueError` here would reach the model as an opaque `-32603` (see below), so a deliberate wire error is raised as `MCPError`: it passes through with its code and message intact, and `-32602` with this text is the spec's own answer for an unknown tool.
6. `params.arguments` can be `None`; v1 defaulted it to `{}` before your code ever saw it. With no validation in front of the handler, this line is load-bearing.
7. An unexpected exception raised here becomes a **sanitized** protocol error, `-32603` `"Internal server error"`: the model never sees the message. For a failure the model should read and react to, return `CallToolResult(is_error=True, ...)`.
8. Handlers are constructor arguments, so the server's surface is complete the moment it exists; `add_request_handler()` is the post-construction escape hatch, and the door to custom methods.

The example is the pattern. More generally: every handler has the same shape, with typed params in and a full result type out; the old jsonschema check of tool arguments is gone; an exception is a protocol error, never an `is_error=True` tool result; and the ambient `server.request_context` ContextVar is gone. Custom, vendor-namespaced methods are first class through `add_request_handler(method, params_type, handler)`, which validates inbound params against your model before your handler runs. And a `middleware` list (deliberately marked provisional) wraps every inbound message, replacing the private `_handle_*` methods people used to override.

Underneath, the v1 `BaseSession` receive loop was replaced by a dispatcher engine that the client and the server now share, and it is what makes several things on this page true at once: one `Server` object serves both protocol eras, `Client(server)` dispatches in process with no JSON-RPC framing, and a timed-out client request now actually cancels the server-side handler.

**[The low-level Server](advanced/low-level-server.md)** is the page; the **[Migration Guide](migration.md#lowlevel-server-decorator-based-handlers-replaced-with-constructor-on_-params)** walks every removed hook. If you never dropped below `MCPServer`, none of this touches you.

### The wire types moved to `mcp-types`, and every field is snake_case

The protocol types now live in their own distribution, `mcp-types`, imported as `mcp_types`. It depends on nothing but pydantic and typing-extensions, so a gateway, a proxy, or a code generator can consume MCP's wire shapes without installing an HTTP stack. `mcp` depends on it at an exact version and re-exports the common names, so `from mcp import Tool` still works; `import mcp.types` does not.

On those types, every Python attribute is now snake_case: `result.is_error`, `tool.input_schema`, `listing.next_cursor`. The JSON on the wire is camelCase, exactly as before; only the attribute spelling changed. Two stricter defaults ride along: unknown fields are ignored instead of round-tripped (put extras in `_meta`), and both sides validate traffic against the protocol version they negotiated. See the **[Migration Guide](migration.md#field-names-changed-from-camelcase-to-snake_case)** for the rename table.

### Transport configuration moved to `run()`

`MCPServer(...)` is about what your server *is*: its name, its instructions, its lifespan, its auth. How it is *served* now belongs to `run()` and the app builders, which is where `host`, `port`, `stateless_http`, `json_response`, the endpoint paths, and `transport_security` went (`MCPServer("x", port=9000)` is a `TypeError`). The overloads are typed per transport, so your editor tells you which options `stdio` takes and which `streamable-http` takes. One removal worth knowing: `mount_path` is gone; mounting the ASGI app is the supported way to serve under a prefix.

**[Running your server](run/index.md)** covers the options; **[Add to an existing app](run/asgi.md)** covers mounting.

### Behavior that changes without an import error

The renames announce themselves. These do not:

* **Sync functions run on a worker thread.** A `def` tool (or resource, prompt, or resolver) no longer blocks the event loop; the trade is that its body no longer runs *on* the event-loop thread, which matters to thread-affine code. `async def` handlers are untouched. **[Migration Guide](migration.md#sync-handler-functions-now-run-on-a-worker-thread)**.
* **`MCPError` (v1's `McpError`) raised inside a tool is a protocol error now.** The model never sees it. Every other exception still becomes an `is_error=True` result the model can read and react to. **[Handling errors](servers/handling-errors.md)** is the split.
* **Results are validated before they leave.** A hand-built `Tool` whose `input_schema` is `{}` now fails `tools/list` (the spec requires `"type": "object"`). Servers built on `@mcp.tool()` never see this; the SDK writes their schemas.
* **Your client validates what it receives.** `list_tools()` and `call_tool()` check the server's answer against the negotiated protocol version, so a not-quite-valid server that v1's lenient parse tolerated now raises `pydantic.ValidationError`. If you connect to servers you do not control, expect to be the one who finds them; the **[Migration Guide](migration.md#client-validates-inbound-traffic-against-the-protocol-schema)** has the details.
* **URI templates are real RFC 6570 now.** `{+path}`, `{?query}` and friends work, matching is exact instead of regex-loose, and path traversal in extracted values is rejected by default. Stricter templates fail at decoration time, not on the first request. **[URI templates](servers/uri-templates.md)**.
* **The streamable HTTP lifespan runs once**, at startup, and its state is shared by every session and request. In v1 it ran once per session, and once per request under `stateless_http=True`. Pools and caches built in a lifespan get dramatically cheaper; anything that acquired a per-connection resource there belongs in the handler body now. **[Lifespan](handlers/lifespan.md)**.
* **`mcp dev` and `mcp install` pin the environment they spawn** to your installed SDK version. Both commands run your server in a fresh `uv run --with ...` environment, which used to resolve `mcp` to the newest stable release rather than the version you are developing against. **[Migration Guide](migration.md#mcp-dev-and-mcp-install-pin-the-spawned-environment-to-your-sdk-version)**.
* **The HTTP client is now `httpx2`, not `httpx`.** The dependency swap changes what your code catches and passes (`httpx2.AsyncClient`, `httpx2.ConnectError`), and it changes how TLS certificates are verified: `httpx2` validates through `truststore` against the operating system trust store instead of certifi's bundled CA list. Most environments never notice; a minimal container with no system CA store, or a private CA that only certifi's bundle knew about, starts failing the TLS handshake. Set `SSL_CERT_FILE`/`SSL_CERT_DIR` or pass `verify=ssl_context` to your client. **[Migration Guide](migration.md#httpx-and-httpx-sse-replaced-by-httpx2)**.

### Removed outright

Each of these is a section in the **[Migration Guide](migration.md)**:

* The **WebSocket transport**, both sides, and the `mcp[ws]` extra. It was never part of the MCP specification.
* The **experimental Tasks** API (`mcp.*.experimental`). 2026-07-28 moves tasks out of the core protocol and into an official extension ([SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2663)), which this SDK does not implement yet.
* `mcp.types`, `mcp.shared.version`, and `mcp.shared.progress` as import paths.
* The deprecated `streamablehttp_client` spelling, and the `get_session_id` callback from `streamable_http_client` (which now yields exactly two streams).
* `McpError`, renamed **`MCPError`** with a direct `(code, message, data)` constructor.
* `MCPServer.get_context()`, `mount_path=`, and the lowlevel `Server`'s decorator methods, ContextVar, and handler dicts.

## The protocol: 2025-11-25 to 2026-07-28

v2 implements the 2026-07-28 revision, and it serves **both** revisions at once: the same `streamable_http_app()` (and the same stdio server) answers a 2025-era client's `initialize` and a 2026-era client's requests with nothing to configure, no flag to flip, and no separate deployment. Serving the new revision does not strand a client on the old one. What follows is what the new revision itself changes.

### No handshake, no session

A 2026-07-28 client does not open a connection, negotiate, and then talk. Every request carries its protocol version, client info, and client capabilities in `_meta`, and the one discovery call, `server/discover`, is a plain request like any other. `Client` does the right thing by default: it probes `server/discover` once and falls back to the `initialize` handshake if the server is older.

Over Streamable HTTP there is no `Mcp-Session-Id` on the 2026 path, which is the operational headline: **nothing ties a modern request to a worker**, so any replica behind a plain round-robin load balancer can answer it. Two honest qualifiers. Your 2025-era clients (today, that is most clients) still open sessions and still need whatever stickiness they needed on v1; nothing changes for them. And the one thing a *multi-round-trip* retry has to carry across workers is its sealed `request_state`, whose default key is minted per process, so a scaled-out deployment passes `RequestStateSecurity(keys=[...])`. (`stateless_http=True` is unrelated: it only affects how 2025-era clients are served, and 2026 traffic never reads it; if you already set it in v1, nothing changes.)

**[Protocol versions](protocol-versions.md)** is the client's side of this, **[Deploy & scale](run/deploy.md)** is the operator's checklist (the Host allowlist, the `request_state` key, notifications across replicas), and **[Serving legacy clients](run/legacy-clients.md)** is the both-eras-at-once story.

### The server cannot call the client: multi-round-trip requests

Every server-initiated request is gone at 2026-07-28: push elicitation, sampling, `roots/list`. On a 2026 connection there is no channel for them, so `ctx.elicit()` and `ctx.session.create_message()` fail there with `NoBackChannelError` (they still work for legacy clients).

The replacement turns the call around. A tool that needs something from the user *returns* the question (`InputRequiredResult`), the client answers it with the same callbacks it always had, and the call is retried with the answers attached. `Client` drives that loop for you. On the server you rarely build the result yourself, because a **[dependency](handlers/dependencies.md)** does it: annotate a parameter with `Resolve(ask_quantity)`, where `ask_quantity` is an ordinary function you write, and the SDK asks over whichever mechanism the connection supports, a live elicitation request on a legacy session or a multi-round-trip on 2026. One tool body, both eras:

```python title="dual_era.py" hl_lines="24 37-38"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

That file is the pitch in one place: one server, one `Resolve`-backed tool, and a legacy client plus a modern client both getting their answer, in memory. **[Multi-round-trip requests](handlers/multi-round-trip.md)** explains the mechanism (including `request_state`, which the SDK seals and verifies for you); **[Elicitation](handlers/elicitation.md)** covers the asking.

!!! warning "This is the one place a ported v1 server changes behavior"
    Your own tests hit it first: `Client(mcp)` negotiates 2026-07-28 against your v2 server by
    default, so a tool that calls `ctx.elicit()` fails in a test that passed on v1. Move the
    question into a `Resolve(...)` parameter (era-portable), or pin the test client to
    `mode="legacy"` if you genuinely want the push behavior.

### Roots, sampling, and protocol logging are deprecated; `ping` is removed

[SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) deprecates three whole *capabilities*, on every protocol version: roots, sampling, and MCP-level logging (`ctx.info()` and friends). That is a separate axis from the missing back-channel above; deprecated is advisory, everything keeps working against 2025-era sessions, and nothing changes on the wire. What you notice is `MCPDeprecationWarning`, which is a `UserWarning`, so it prints by default; expect your first `ctx.info(...)` after the upgrade to say so.

`ping` is stricter: removed from the protocol, not deprecated. Two of the deprecated features' standalone methods are removed at 2026-07-28 the same way, `logging/setLevel` and the client's `notifications/roots/list_changed`, and progress notifications are now server-to-client only.

**[Deprecated features](deprecated.md)** has the full table, the replacement for each, and the one-line filter if you need a quiet log while you serve legacy clients.

### Change notifications become one stream

At 2026-07-28 the standalone HTTP GET stream and `resources/subscribe` are replaced by `subscriptions/listen`: the client opens one long-lived stream and names the notification kinds it wants. `MCPServer` serves it out of the box; you publish with `await ctx.notify_resource_updated(uri)` (and `notify_tools_changed()`, and so on), and multi-replica deployments plug in a shared `SubscriptionBus`. On the client (since `2.0.0b2`), `async with client.listen(...)` opens the stream: the filter goes in as keyword arguments, typed change events come back, and `sub.honored` is the subset the server agreed to deliver. One honest caveat: over stdio the server does not serve the stream yet.

**[Subscriptions](handlers/subscriptions.md)** covers publishing and serving, **[its Clients twin](client/subscriptions.md)** the watching end, and **[Deploy & scale](run/deploy.md)** the bus.

### The rest, quickly

* **Identity is optional, per-message metadata.** The request-side `clientInfo` `_meta` key is optional (the required pair is `protocolVersion` + `clientCapabilities`), and `serverInfo` moved out of the `server/discover` result body: servers stamp it into every 2026-era result's `_meta` instead (since `2.0.0b3`; [spec #3002](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/3002)). The SDK always stamps; `client.server_info` is `None` when a server does not identify itself (for example, a middleware stripped the key). **[The low-level Server](advanced/low-level-server.md)** shows the stamp on the wire.
* **Requests are routable without parsing bodies.** Modern HTTP requests carry `Mcp-Method` (and, for the three tool-ish calls, `Mcp-Name`); a tool input-schema property annotated with `x-mcp-header` is mirrored into an `Mcp-Param-*` header and cross-checked by the server ([SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243)). Gateways and rate limiters can route on headers alone; the **[Migration Guide](migration.md#servers-validate-mcp-param-headers-against-the-request-body-sep-2243)** has the rules.
* **Results carry cache hints.** List and read results declare `ttlMs` and `cacheScope` ([SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549)); you set them per method with `cache_hints=`, and `Client` honors them with a built-in response cache. A server that sends no hints (every pre-2026 server) sees identical, uncached traffic. **[Caching hints](client/caching.md)**.
* **Extensions are first class.** Servers and clients declare optional capability bundles under reverse-DNS identifiers ([SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)); the built-in `Apps` extension (MCP Apps) is the reference. **[Extensions](advanced/extensions.md)** and **[MCP Apps](advanced/apps.md)**.
* **Error codes got standardized.** A missing resource is `-32602` with the URI in `error.data`, and the new spec-reserved codes appear as `-32020` (header mismatch), `-32021` (missing required capability), and `-32022` (unsupported protocol version). **[Troubleshooting](troubleshooting.md)** is keyed by the exact messages.
* **Authorization got harder to hold wrong.** The client validates the `iss` returned with the authorization code ([RFC 9207](https://datatracker.ietf.org/doc/html/rfc9207); your `callback_handler` now returns an `AuthorizationCodeResult`), sends `application_type` when it registers, and never replays credentials against a different authorization server. New in the enterprise corner: the [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) identity-assertion flow. The **[Migration Guide](migration.md)** lists every OAuth change; **[OAuth for clients](client/oauth-clients.md)** and **[Identity assertion](client/identity-assertion.md)** are the pages.
* **Every server is traceable.** OpenTelemetry ships on by default as middleware: every request gets a server span, at no cost until the process configures an exporter. When both ends run the SDK, the client also propagates W3C trace context in `_meta`, so the traces join up. **[OpenTelemetry](run/opentelemetry.md)**.

## Upgrading from v1?

* The **[Migration Guide](migration.md)** is the complete, exact list of what to change; this page was the why.
* **v1.x is not going anywhere.** It stays the stable line, with critical fixes and security patches, and nothing about the 2026-07-28 spec release breaks it. If you publish a library that depends on `mcp`, add an upper bound (for example `mcp>=1.27,<2`) so stable v2 does not surprise your users.
* Something rough, confusing, or broken? **[File v2 feedback](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)**; it all gets read.
