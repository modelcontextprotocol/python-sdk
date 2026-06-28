# Lifespan

Most real servers hold something for their whole life: a database pool, an HTTP client, a loaded model.

You don't want to build it on every call, and you do want to close it cleanly. That's what the **lifespan** is for.

## A typed lifespan

A lifespan is an `@asynccontextmanager` that receives the server and `yield`s **one object**. Whatever you yield is available to every handler for as long as the server runs.

```python title="server.py" hl_lines="25-31 34 38 40"
--8<-- "docs_src/lifespan/tutorial001.py"
```

Read it bottom-up:

* `app_lifespan` connects the `Database` **before** the `yield` and disconnects it **after**, in a `finally`. That's startup and shutdown.
* It yields an `AppContext`, a plain dataclass holding the things you set up. One field today, ten tomorrow.
* `MCPServer("Bookshop", lifespan=app_lifespan)` is the whole wiring.
* Inside the tool, the yielded object is `ctx.request_context.lifespan_context`.

The lifespan runs **once**. It is entered when the server starts (before the first request) and exited when the server stops. Every request in between shares the same `AppContext`.

!!! info
    If you've written a FastAPI `lifespan`, you already know this. Same decorator, same `yield`, same `finally`.

### What the model sees

Nothing new. `ctx` is a **Context** parameter, so the SDK injects it and it never reaches the input schema:

```json
{
  "type": "object",
  "properties": {
    "genre": {"title": "Genre", "type": "string"}
  },
  "required": ["genre"],
  "title": "count_booksArguments"
}
```

`genre` is the only argument the model can pass. The lifespan is your server's business.

`@mcp.resource()` and `@mcp.prompt()` functions can take a `ctx` parameter too, written as a bare `Context` for a reason the next section gets to. Everything `ctx` carries is in **[The Context](context.md)**.

### It really is typed

Look at the annotation again: `ctx: Context[AppContext]`.

That one type parameter is why `ctx.request_context.lifespan_context` **is** an `AppContext` to your type checker. `.db` autocompletes; `.dbb` is an error before you ever run the server.

Write a bare `Context` instead and `lifespan_context` is typed as `dict[str, Any]`: the type checker has no way to know what your lifespan yielded. The object is still there at runtime; you've lost the help.

!!! warning
    `Context[AppContext]` is a **tool-only** spelling. Put it on an `@mcp.resource()` or
    `@mcp.prompt()` function and every call to that handler fails. The client gets an error back,
    and the server log shows why:

    ```text
    Context is not available outside of a request
    ```

    In resources and prompts, write the bare `ctx: Context`. The object your lifespan yielded is
    still `ctx.request_context.lifespan_context` at runtime; you give up the type parameter, not
    the object.

!!! tip
    There is always a lifespan. If you don't pass one, the SDK's default yields an empty `dict`,
    so `ctx.request_context.lifespan_context` is `{}`, never `None`. That default is also why a
    bare `Context` types it as `dict[str, Any]`.

## Watch it happen

"Startup runs before the first request" is the kind of sentence you should not have to take on faith.

Strip the server down to the lifecycle: give `Database` a `connected` flag, flip it in `connect()` and `disconnect()`, and add a tool that reports it.

```python title="server.py" hl_lines="11 14 17 25 44"
--8<-- "docs_src/lifespan/tutorial002.py"
```

`database` lives at module level for one reason: so you can look at it from *outside* the server.

!!! check
    Three moments, three values:

    * Before the server starts, `database.connected` is `False`. Importing the module connected nothing.
    * While it's running, call `database_status` and the result is `"connected"`.
    * Stop the server and the `finally` block runs: `database.connected` is `False` again.

    The work happened exactly where you put it: around the `yield`, not at import time and not per request.

## Recap

* `lifespan=` takes an `@asynccontextmanager` that receives the server and `yield`s one object.
* Code before the `yield` is startup. The `finally` after it is shutdown.
* It runs once, around the whole life of the server, not per request.
* Whatever you `yield` is `ctx.request_context.lifespan_context` in every tool, resource, and prompt.
* `ctx: Context[AppContext]` makes that access fully typed in tools. Resources and prompts take the bare `Context`.
* No `lifespan=` means an empty `dict`, never `None`.

Next: tools that return more than text, **[Media](media.md)**.
