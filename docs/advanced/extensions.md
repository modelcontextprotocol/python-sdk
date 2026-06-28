# Extensions

An **extension** is an opt-in bundle of MCP behaviour behind one identifier.

It can contribute tools, resources, and new request methods, and it can wrap `tools/call`.
The server advertises it under `capabilities.extensions`, the client opts in the same way,
and nothing changes for anyone who didn't ask for it. That is the contract (SEP-2133), and
it has one golden rule: **extensions are off by default**.

## Using an extension

Pass instances at construction:

```python
from mcp.server.apps import Apps
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("demo", extensions=[Apps()])
```

Done. The server now advertises `io.modelcontextprotocol/ui` under
`capabilities.extensions` and serves everything the extension contributes.

`Apps` is the built-in reference extension, and it gets its own page: **[MCP Apps](apps.md)**.

!!! note
    Extensions are fixed at construction. There is no `add_extension` to call later:
    a server's capability map should not change while clients are connected to it.

The capability map rides `server/discover`, which is a **2026-07-28** path. A legacy
`initialize` handshake has nowhere to put it, so a legacy client simply doesn't see
the extension. Design for that: an extension *augments* a server, it must not be the
only way the server is usable.

## Writing your own

Subclass `Extension` and override only what you need. Every method has a default.

### The identifier

```python
class Stamps(Extension):
    identifier = "com.example/stamps"
```

The identifier is a `vendor-prefix/name` string following the spec's `_meta` key
grammar: dot-separated labels (each starts with a letter, ends with a letter or
digit), a slash, then the name. It is validated **when the class is defined**, so a
typo doesn't wait for a server to boot:

```text
TypeError: Stamps.identifier must be a `vendor-prefix/name` string
(reverse-DNS prefix required), got 'stamps'
```

Use a domain you control as the prefix. `io.modelcontextprotocol/*` is for extensions
specified by the MCP project itself.

### Contributing tools

The smallest useful extension is one tool and a settings map:

```python title="server.py" hl_lines="16 18-19 21-22 25"
--8<-- "docs_src/extensions/tutorial001.py"
```

* `tools()` returns `ToolBinding`s. The server registers each one exactly as if you
  had called `mcp.add_tool(...)` yourself: same schema generation, same `Context`
  injection, same everything.
* `settings()` is the value advertised at `capabilities.extensions["com.example/stamps"]`.
  Return `{}` (the default) to advertise the extension with no settings.
* The extension never receives the server. It declares contributions as data;
  `MCPServer` consumes them. There is no `self.server` to mutate.

#### Try it

```python
from mcp import Client


async def main() -> None:
    async with Client(mcp) as client:
        print(client.server_capabilities.extensions)
        # {'com.example/stamps': {'sealed': True}}
        result = await client.call_tool("stamp", {"text": "hello"})
        # [stamped] hello
```

### Serving your own methods

An extension can register **new request methods**: its own verbs, served next to the
spec's:

```python title="server.py" hl_lines="14-20 24 33-41"
--8<-- "docs_src/extensions/tutorial002.py"
```

* `SearchParams` subclasses `RequestParams`, so the 2026 `_meta` envelope parses
  uniformly and your handler gets validated params, never a raw dict. Bound what
  the client controls: `Field(ge=1, le=100)` rejects an absurd `limit` before
  your code allocates anything for it.
* `require_client_extension(ctx, EXTENSION_ID)` is the gate: a client that did not
  declare the extension gets the `-32021` (missing required client capability) error,
  with the machine-readable `requiredCapabilities` payload the spec asks for.
* `protocol_versions=frozenset({"2026-07-28"})` pins the method to one wire version.
  At any other version the client gets `METHOD_NOT_FOUND`, exactly as if the method
  didn't exist there. For that client, it doesn't.

Methods are **strictly additive**. The SDK enforces this at construction, not at
runtime:

* A `MethodBinding` for a spec-defined method (`tools/list`, `completion/complete`, ...)
  raises `ValueError` when the binding is constructed. Core verbs belong to the server.
* Two extensions binding the same method raise when the second one registers.
  Last-write-wins is how plugins corrupt each other; we don't do that.
* An empty `protocol_versions` set raises too: a method that can never be served
  is a bug, not a configuration.

!!! tip
    Calling a vendor method from the client goes through `client.session.send_request(...)`
    today; `Client` only grows first-class methods for spec verbs. The
    `custom_methods` story in `examples/stories/` shows the full round trip.

### Intercepting `tools/call`

The one interceptive hook. Override `intercept_tool_call` to observe, short-circuit,
or veto a tool call:

```python title="server.py" hl_lines="18-25"
--8<-- "docs_src/extensions/tutorial003.py"
```

* `params` is the validated `CallToolRequestParams`: you get `params.name` and
  `params.arguments` without touching raw JSON.
* `call_next(ctx)` runs the rest of the chain. Return its result unchanged (observe),
  return something else (replace), or raise an `MCPError` (refuse).
* With several extensions, interceptors nest in registration order: the first
  extension in `extensions=[...]` is outermost.
* The default implementation is a pass-through, and a server whose extensions never
  override this hook installs **no** middleware at all. You don't pay for what
  you don't use.

The hook wraps `tools/call` and nothing else. For every-message concerns, use
[Middleware](middleware.md). That is what it is for.

## The client side

A client declares the extensions it supports the same way the server does:

```python
from mcp import Client

async with Client(target, extensions={"com.example/search": {}}) as client:
    ...
```

That map becomes `ClientCapabilities.extensions`. On a 2026-07-28 connection it
travels in the per-request `_meta` envelope, so the server sees it on **every**
request; on a legacy connection it rides the `initialize` handshake. Server code
doesn't care which: `require_client_extension(ctx, ...)` and
`ctx.session.check_client_capability(...)` read the right source on both paths.

## What an extension cannot do

The contribution surface is **closed** on purpose: settings, tools, resources,
methods, one `tools/call` interceptor. An extension cannot:

* **Reach into the server.** It declares data; it holds no server reference.
* **Replace core behaviour.** Spec methods are rejected at construction, and
  `initialize` is reserved by the runner outright.
* **Register late.** After `MCPServer(...)` returns, the extension set is what it is.

If you are fighting these walls, you are not writing an extension. You are writing
a fork. The walls are the feature: a user reading `extensions=[Apps(), Stamps()]`
knows *everything* those two can have touched.
