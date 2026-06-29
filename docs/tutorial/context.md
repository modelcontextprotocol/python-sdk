# The Context

A tool's arguments come from the model. Everything else (the request you are serving, the server you live in, a way to talk back to the client) comes from one object: the **`Context`**.

You don't construct it and you don't configure it. You ask for it.

## Ask for it

Add a parameter annotated with `Context` to any tool:

```python title="server.py" hl_lines="2 8"
--8<-- "docs_src/context/tutorial001.py"
```

* The SDK builds a fresh `Context` for every request and passes it in.
* The parameter **name doesn't matter**. `ctx`, `context`, `c`: the SDK finds it by its annotation.
* Resources and prompts can declare one too, the same way.
* `ctx.request_id` is the id of the request your function is serving right now.

!!! info
    If you've used FastAPI, you've seen this move: declare a parameter with the framework's own type
    (`Request` there, `Context` here) and the framework supplies it. Nothing to register, nothing to
    configure: the type annotation is the whole mechanism.

### Invisible to the model

This is the part to internalise. Here is the input schema `tools/list` reports for `search_books`:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

One property. `ctx` is not an argument: it never appears in the schema, the model is never told about it, and no client can fill it in. It's a contract between you and the SDK, invisible on the wire.

### Try it

Run the server with the MCP Inspector:

```console
uv run mcp dev server.py
```

The form for `search_books` has a single `query` field. Call it with `dune`:

```text
[request 3] Found 3 books matching 'dune'.
```

The number is whichever request this happened to be. Call the tool again and it changes: every request gets its own `Context`.

## What it gives you

The injected object is small. Besides `request_id`:

* `await ctx.read_resource(uri)`: read one of the server's **own** resources from inside a tool. The next section.
* `await ctx.report_progress(progress, total, message)`: stream progress back to the caller during a long call. The whole story is in **Progress**.
* `await ctx.elicit(message, schema)` and `await ctx.elicit_url(...)`: pause the tool and ask the user a question. That's **Elicitation**.
* `ctx.session`: the server's side of the conversation with this client. Notifications you send to the client live here; the last section uses it.
* `ctx.headers`: the request headers the transport carried, or `None` on stdio. Read a custom header with `(ctx.headers or {}).get("x-...")`. Headers are client-supplied input - fine for a locale or a feature flag, never an identity.
* `ctx.request_context`: the raw per-request record. The field you'll reach for is `lifespan_context`, the object your startup code yielded (see **Lifespan**).

Logging is deliberately not on that list. A server logs with Python's `logging` module, like any other Python program. **Logging** is the short chapter on why.

!!! tip
    Injection only happens for the function you registered. A helper that your tool calls doesn't get
    its own `Context`; pass `ctx` down as an ordinary argument. There is no ambient
    "current context" to fetch from somewhere else.

## Read your own resources

A server's resources aren't only for clients. A tool can read them too:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/context/tutorial002.py"
```

`ctx.read_resource` resolves the URI through the same registry that serves `resources/read`, so a tool gets what a client would get: an iterable of `ReadResourceContents`, one per content block. For this URI there is one:

```python
contents.content    # 'fiction, non-fiction, poetry'
contents.mime_type  # 'text/plain'
```

* `content` is exactly what `genres()` returned. One source of truth: the client browses the resource, your tools consume it, nobody copies the string.
* `describe_catalog`'s only parameter is the `Context`, so its input schema has **no properties at all**. The model calls it with `{}`.

## Tell the client the list changed

What a server offers is not fixed at import time. Register a tool at runtime, then tell the client:

```python title="server.py" hl_lines="15-16"
--8<-- "docs_src/context/tutorial003.py"
```

* `mcp.add_tool(recommend_book)` registers a plain function as a tool: name, description and schema derived exactly as `@mcp.tool()` would have.
* `await ctx.session.send_tool_list_changed()` sends `notifications/tools/list_changed`. A client that receives it calls `tools/list` again and sees `recommend_book`.

The siblings are `send_resource_list_changed()`, `send_prompt_list_changed()`, and `send_resource_updated(uri)` for a change to one specific resource.

!!! check
    Before anyone runs `enable_recommendations`, the tool you are promising does not exist. Call it
    anyway and the result is an error the model can read:

    ```text
    Unknown tool: recommend_book
    ```

    Run `enable_recommendations`, and the very same call succeeds. The tool list is genuinely
    dynamic: `tools/list` reflects whatever is registered *right now*.

## Recap

* Annotate a parameter with `Context` (in a tool, a resource, or a prompt) and the SDK injects it. The name is yours.
* It is invisible to the model: the input schema only ever contains your real arguments.
* `ctx.request_id` identifies the request; `ctx.request_context.lifespan_context` is what your startup yielded.
* `await ctx.read_resource(uri)` lets a tool read the server's own resources.
* `ctx.session` is the channel back to the client: `send_tool_list_changed()` and its siblings tell it to re-fetch a list you changed.
* Progress reporting and elicitation also start at `Context`; each has its own chapter.

Next: parameters the model never sees, filled by your own functions, in **Dependencies**.
