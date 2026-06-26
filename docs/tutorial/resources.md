# Resources

A **resource** is data you expose for the application to read.

That's the split. A tool is something the **model** decides to call. A resource is something the **application** decides to load (a config file, a record, a document) and put in front of the model as context.

You declare one by putting `@mcp.resource(uri)` on a plain Python function.

## Your first resource

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/resources/tutorial001.py"
```

It's the same shape as a tool, plus one thing: the **URI**. Resources are addressed, not named. A client asks for `config://app`, never for `get_config`.

The SDK still reads the rest from the function:

* The **name** is the function name: `get_config`.
* The **description** the client sees is the docstring.
* The **content** is whatever you return.

During `resources/list` the client gets this:

```json
{
  "name": "get_config",
  "uri": "config://app",
  "description": "The active shop configuration.",
  "mimeType": "text/plain"
}
```

And when it reads `config://app`, your function runs and the return value comes back as text:

```python
result.contents  # [TextResourceContents(uri="config://app", mime_type="text/plain", text="theme=dark\nlanguage=en")]
```

!!! tip
    Listing is cheap. Your function is **not** called during `resources/list`, only during
    `resources/read`, and only for the URI that was asked for. Expose a thousand resources
    and you pay for the ones somebody opens.

### Try it

Run the server with the MCP Inspector:

```console
uv run mcp dev server.py
```

Open the URL it prints and go to the **Resources** tab. `config://app` is in the list with its description. Click it and the Inspector reads it: there are your two lines of config.

## Resource templates

One URI per record doesn't scale. Put a **placeholder** in the URI and a matching parameter on the function:

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/resources/tutorial002.py"
```

`{user_id}` in the URI, `user_id: str` on the function. That is the entire contract.

This is now a **resource template**, and it moves house: it leaves `resources/list` and shows up in `resources/templates/list` instead, as a pattern rather than an address:

```json
{
  "name": "get_user_profile",
  "uriTemplate": "users://{user_id}/profile",
  "description": "A customer's profile.",
  "mimeType": "text/plain"
}
```

The client fills in the placeholder and reads a concrete URI: `users://42/profile`, `users://ada/profile`. One function answers all of them, with the matched value passed in as `user_id`:

```python
result.contents  # [TextResourceContents(uri="users://42/profile", text="User 42: 12 orders since 2021.")]
```

Notice the `uri` in the result. It is the **concrete** URI the client asked for, not the template.

!!! check
    The placeholders and the parameters have to agree. Rename the function parameter to
    `user` while the URI still says `{user_id}` and the decorator refuses **at import time**,
    before any client gets near it:

    ```text
    ValueError: Mismatch between URI parameters {'user_id'} and function parameters {'user'}
    ```

    A mismatch can only ever be a bug, so the SDK makes it impossible to start the server with one.

`get_user_profile` can also take a parameter annotated `Context`. The SDK injects it without ever treating it as a URI parameter, and **The Context** chapter covers what it gives you.

## What you return

You're not limited to `str`. Give each resource a `mime_type` and return whatever fits:

```python title="server.py" hl_lines="8-9 14-15 20-21"
--8<-- "docs_src/resources/tutorial003.py"
```

* `readme` returns a `str`, so it's sent as-is. This is the common case.
* `catalog_stats` returns a `dict`, so the SDK serialises it to **JSON text** for you:

    ```json
    {
      "books": 1204,
      "authors": 391
    }
    ```

* `placeholder_cover` returns `bytes`, so the client gets a `BlobResourceContents` instead of a `TextResourceContents`, with your bytes base64-encoded in its `blob` field.

The same rule applies to anything else JSON-serialisable: a list, a Pydantic model, a dataclass. If it isn't a `str` and isn't `bytes`, it becomes JSON.

`mime_type` is yours to declare, and it defaults to `text/plain`. The SDK never inspects what you return to guess it, so a `dict` resource you don't label is still advertised as plain text.

!!! tip
    `name=`, `title=` and `description=` are also accepted by `@mcp.resource()` when you don't
    want to derive them from the function. And when there's no function to write at all,
    `mcp.server.mcpserver.resources` has ready-made `Resource` classes (`TextResource`,
    `BinaryResource`, `FileResource`, `HttpResource`, `DirectoryResource`) that you register
    with `mcp.add_resource(...)`.

A client can also **subscribe** to a resource and be notified when it changes; that's the client's half of the story and it lives in **The Client**.

## Recap

* `@mcp.resource(uri)` on a function makes it a resource. The URI is the address, the return value is the content, the docstring is the description.
* A `{placeholder}` in the URI makes it a **template**: it's listed under `resources/templates/list` and one function serves every URI that matches.
* Placeholder names must equal the function's parameter names. Get it wrong and you find out at import time, not in production.
* Your function runs when the resource is **read**, not when it's listed.
* `str` becomes text, `bytes` becomes a base64 blob, anything else becomes JSON text. `mime_type=` is how you label it.
* Tools are for the model to act. Resources are for the application to read.

Next: the third primitive, the one a person picks from a menu, **Prompts**.
