# The low-level Server

`@mcp.tool()` is a layer. Underneath it is a second server class, `Server`, that speaks raw MCP: you hand it the protocol objects and it puts them on the wire, unchanged.

`MCPServer` is built on top of it. You drop down when the convenience layer is in the way:

* You need to emit an **exact** schema (loaded from a file, generated from a database), not one derived from a Python signature.
* You need full control of the result: `_meta`, `is_error`, every key of `structured_content`.
* You need to handle a method MCP doesn't define.

For everything else, stay on `MCPServer`.

## The same tool, by hand

This is the `search_books` tool that **[Tools](../servers/tools.md)** writes in nine lines of `@mcp.tool()`, with the sugar removed:

```python title="server.py" hl_lines="23 27 33"
--8<-- "docs_src/lowlevel/tutorial001.py"
```

Three things changed, and they are the whole low-level API:

* **Handlers are constructor parameters.** `on_list_tools=` and `on_call_tool=` go into `Server(...)`. There are no decorators down here, and every handler has the same shape: `async (ctx, params) -> result`.
* **You write the input schema.** `Tool.input_schema` is a plain JSON Schema `dict`. Nobody derives it from type hints, because there are no type hints to derive it from.
* **You build the result.** `CallToolResult(content=[TextContent(...)])`, by hand. Nothing is wrapped, converted, or inferred from a return annotation.

`params` is the parsed request: `CallToolRequestParams` gives you `.name` and `.arguments`. `ctx` is a `ServerRequestContext`: `ctx.session` for talking back to the client, `ctx.lifespan_context`, `ctx.request_id`, and `ctx.meta`, the request's inbound `_meta`.

!!! info
    If you've used FastAPI, you already know this relationship. `MCPServer` is the decorators-and-type-hints layer; `Server` is the Starlette underneath. They are not rivals: `MCPServer` constructs a `Server` and registers handlers exactly like these on it.

### Try it

There is no Inspector for this one: `mcp dev` and `mcp run` only accept an `MCPServer`. The in-memory `Client` doesn't care; it takes a low-level `Server` exactly like it takes an `MCPServer`:

```python title="main.py"
import asyncio

from mcp import Client

from server import server


async def main() -> None:
    async with Client(server) as client:
        result = await client.call_tool("search_books", {"query": "dune", "limit": 5})
        print(result.content)


asyncio.run(main())
```

```text
[TextContent(type='text', text="Found 3 books matching 'dune' (showing up to 5).", annotations=None, meta=None)]
```

The same text the `@mcp.tool()` version produced. Two honest differences:

* `result.structured_content` is `None`. The high-level server wraps a `-> str` into `{"result": ...}` for you; here nobody builds what you didn't build.
* `list_tools` returns the schema **you** typed, character for character. The high-level version had `"title": "Query"` on every property and a `"title": "search_booksArguments"` at the root: Pydantic artifacts. Down here, if it's on the wire, you put it there.

## Nothing is checked for you

`MCPServer` rejects a bad argument before your function ever runs, validating the call against the schema it generated (**[Tools](../servers/tools.md)**).

`Server` does not do that. Your `input_schema` is *advertised* to the client; it is never *applied* to `params.arguments`.

!!! check
    Call `search_books` without `limit` and your `args["limit"]` raises `KeyError`. The client sees:

    ```text
    MCPError: Internal server error
    ```

    A JSON-RPC error, code `-32603`, with a deliberately generic message: the SDK won't leak your traceback to a remote caller. The model never finds out what it did wrong, so it can't retry. (In a test, `raise_exceptions=True` surfaces the real exception instead; see **[Testing](../get-started/testing.md)**.)

That generalises. An exception raised from a low-level handler is **always** a protocol error, never an `is_error=True` tool result. If you want the model to read the failure and recover, validate `params.arguments` yourself and return `CallToolResult(content=[TextContent(...)], is_error=True)`. The two kinds of failure are the subject of **[Handling errors](../servers/handling-errors.md)**.

## Two tools, one handler

`on_call_tool` is the single entry point for every tool on the server. You route on `params.name`:

```python title="server.py" hl_lines="39-44"
--8<-- "docs_src/lowlevel/tutorial002.py"
```

* `list_tools` advertises both. `call_tool` dispatches on the name.
* The `else` branch matters: `Server` will happily forward a `tools/call` for a name you never listed straight into your handler. Raising there turns the call into the same `-32603` as above.

## Structured output, by hand

Declare `output_schema` on the `Tool` and put `structured_content` on the result. Both are yours:

```python title="server.py" hl_lines="20-24 37"
--8<-- "docs_src/lowlevel/tutorial003.py"
```

Call it and the result carries both representations:

```json
{
  "content": [{"type": "text", "text": "Found 3 books matching 'dune'."}],
  "structuredContent": {"matches": 3, "query": "dune"},
  "isError": false,
  "resultType": "complete",
  "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "Bookshop", "version": "2.0.0"}}
}
```

The `_meta` block is the server's identity stamp: the SDK adds it to every 2026-era result, with the `version` taken from the constructor or the installed package. Pass `include_server_info=False` to the server to turn it off.

The server never compares the two fields. This SDK's `Client` does: return `structured_content` that doesn't satisfy the `output_schema` you declared and `call_tool` raises a `RuntimeError` that starts with `Invalid structured content returned by tool search_books` and goes on to quote the `jsonschema` failure. Promising a schema is cheap; keeping it is on you. The whole ladder of return types and schemas is in **[Structured Output](../servers/structured-output.md)**.

## `_meta`: for the application, not the model

`content` is the part of the answer the model reads. `structured_content` is the same answer as typed data. `_meta` is the third channel: data that rides along with the result for the **client application**, without being part of the answer at all.

Use it for record IDs, trace IDs, anything your UI needs and your prompt doesn't:

```python title="server.py" hl_lines="38"
--8<-- "docs_src/lowlevel/tutorial004.py"
```

* You construct it as `_meta=`, the wire name. The client reads it back as `result.meta`.
* Namespace your keys (`bookshop/record_ids`). The `io.modelcontextprotocol/*` keys are reserved by the protocol.

!!! warning
    `_meta` is a convention between you and the client application, not a guarantee about what reaches
    the model. The host decides what it renders. Never put a secret in any part of a tool result.

## Capabilities follow your handlers

A `Server` advertises exactly the method families you gave it handlers for. The `Bookshop` above passes `on_list_tools` and `on_call_tool` and nothing else, so a client connecting to it sees:

```json
{"tools": {"listChanged": false}}
```

No `resources`, no `prompts`: there is nothing to back them. Pass `on_list_prompts` and `prompts` appears; pass `on_completion` and `completions` appears.

`MCPServer` always advertises tools, resources and prompts, whether you registered any or not, because its managers always exist. Down here the declaration *is* the constructor call.

## The lifespan generic

`Server` is generic in the type its lifespan yields. Annotate it once and the object is typed everywhere it surfaces:

```python title="server.py" hl_lines="25-27 45-46 51"
--8<-- "docs_src/lowlevel/tutorial005.py"
```

* The lifespan is a `Callable[[Server[Catalog]], AbstractAsyncContextManager[Catalog]]`; `@asynccontextmanager` on an `async` generator gives you exactly that.
* Whatever it `yield`s becomes `ctx.lifespan_context`, and because the handlers are annotated `ServerRequestContext[Catalog]`, `.search(...)` autocompletes and type-checks.
* It is entered once when the server starts and exited once when it stops. Startup, teardown, and `MCPServer`'s version of the same idea are in **[Lifespan](../handlers/lifespan.md)**.

Without a `lifespan=`, `ctx.lifespan_context` is an empty `dict`.

## A method of your own

The constructor covers the methods MCP defines. `add_request_handler` covers everything else:

```python title="server.py" hl_lines="35-36 39-40 43-44 48"
--8<-- "docs_src/lowlevel/tutorial006.py"
```

* The first argument is the method string. Notifications have a twin, `add_notification_handler`.
* `params_type` is the model the incoming `params` are validated against **before** your handler runs, so custom methods *do* get the validation tools don't. Subclass `RequestParams` so the `_meta` field parses like every other method's.
* The handler returns a `BaseModel`, a `dict`, or `None`. The SDK serialises it into the JSON-RPC result.

One honest caveat: the high-level `Client` only has verbs for the methods MCP defines, so there is no `client.reindex()`. A vendor method is for a peer that already knows it exists: a client you also ship, or another service of yours speaking JSON-RPC.

One method you cannot claim:

```text
ValueError: 'initialize' is handled by the server runner and cannot be overridden;
use Server.middleware to observe or wrap initialization
```

The handshake belongs to the runner. `server/discover`, `ping`, and every other built-in are yours to replace.

!!! tip
    `Server.middleware`, mentioned in that error, wraps **every** inbound message, including `initialize`. If what you want is to observe or rewrite traffic rather than answer a new method, start at **[Middleware](middleware.md)**.

## The other handlers

Each of these is one idea you now have the vocabulary for; each has its own page.

* `on_call_tool`, `on_get_prompt`, and `on_read_resource` may return an `InputRequiredResult` instead of their normal result to pause the call and ask the client for input; see **[Multi-round-trip requests](../handlers/multi-round-trip.md)**. True to this tier, nothing is installed for you: where `MCPServer` seals `requestState` by default, here the `request_state` you set crosses the wire exactly as written until you opt in with `server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[...]), default_audience=server.name))`: one line (both names import from `mcp.server.request_state`) for the identical sealing and verification `MCPServer` performs (**[Protecting `requestState`](../handlers/multi-round-trip.md#protecting-requeststate)**).
* `on_list_resources`, `on_read_resource`, `on_list_prompts`, `on_get_prompt`, `on_completion` are the same `(ctx, params) -> result` shape for the other primitives.
* `on_subscriptions_listen` serves the 2026-07-28 `subscriptions/listen` stream. Pass a `ListenHandler` built over a `SubscriptionBus` and publish events to the bus from your other handlers; see **[Subscriptions](../handlers/subscriptions.md)** for the full composition.
* `server.streamable_http_app()` returns the same Starlette app `MCPServer`'s does; deploy it the way **[Running your server](../run/index.md)** deploys any other ASGI app. There is no `server.run(transport=...)` down here: `server.run(read_stream, write_stream, server.create_initialization_options())` drives one connection over a pair of streams, and that one line is the whole story.

## Recap

* The low-level `Server` takes its handlers as `on_*` **constructor parameters**; every handler is `async (ctx, params) -> result`.
* You write the `input_schema` dict and you build the `CallToolResult`. Nothing is derived, wrapped, or validated for you.
* An exception in a handler is a `-32603` protocol error. A tool error the model can read is a `CallToolResult` with `is_error=True` that **you** return.
* `_meta` on the result is addressed to the client application, not the model.
* `Server[T]` is generic in what its lifespan yields; `ctx.lifespan_context` is a typed `T`.
* `add_request_handler(method, params_type, handler)` serves any method. `initialize` is reserved.
* The capabilities a `Server` advertises are derived from which handlers you registered.

`Client(server)` treated both servers identically because they *are* the same protocol, which is the whole point. The next layer down isn't a class at all: it's **[Middleware](middleware.md)**.
