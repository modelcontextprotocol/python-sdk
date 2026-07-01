# Tools

A **tool** is a function the model can call.

You declare one by putting `@mcp.tool()` on a plain Python function. That's the whole API.

## Your first tool

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/tools/tutorial001.py"
```

Look at what you wrote. There are no schemas, no JSON, no protocol, just a function. The SDK reads three things from it:

* The **name** of the tool is the name of the function: `search_books`.
* The **description** the model sees is the docstring: `Search the catalog by title or author.`
* The **arguments** the model is allowed to pass come from the type hints: `query: str` and `limit: int`.

### The input schema

From those type hints the SDK generates a JSON Schema and sends it to the client during `tools/list`:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"title": "Limit", "type": "integer"}
  },
  "required": ["query", "limit"],
  "title": "search_booksArguments"
}
```

Both arguments are in `required` because neither has a default. You'll fix that in a moment. (The `title` keys are Pydantic artifacts; the properties, their types, and `required` are the contract.)

!!! tip
    Type hints aren't documentation here. They are **the contract**. If a client sends `"limit": "ten"`,
    the SDK rejects it before your function ever runs.

### What the model gets back

Call the tool with `{"query": "dune", "limit": 5}` and the result has two parts:

```python
result.content             # [TextContent(text="Found 3 books matching 'dune' (showing up to 5).")]
result.structured_content  # {'result': "Found 3 books matching 'dune' (showing up to 5)."}
```

`content` is the text the **model** reads. `structured_content` is typed data for the **client application**. It's there because you declared the return type as `-> str`.

Don't worry about `structured_content` yet. Return real Python objects from your tools and the right thing happens; the **[Structured Output](structured-output.md)** page is all about it.

### Try it

Run the server with the MCP Inspector:

```console
uv run mcp dev server.py
```

Open the URL it prints, go to the **Tools** tab, and call `search_books`.

The Inspector renders a form with a required `query` text field and a required `limit` number field. It built that form from your type hints. So will every other MCP client.

## Optional arguments

Give a parameter a default value and it stops being required. That's it. It's just Python.

```python title="server.py" hl_lines="7"
--8<-- "docs_src/tools/tutorial002.py"
```

The schema follows:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"default": 10, "title": "Limit", "type": "integer"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

`limit` left `required` and gained `"default": 10`. A client that omits it gets `10`, exactly as Python would.

## Richer schemas with `Field`

Type hints get you a long way, but sometimes you want to *describe* an argument, or constrain it.

Wrap the type in `Annotated` and add a Pydantic `Field`:

```python title="server.py" hl_lines="12-14"
--8<-- "docs_src/tools/tutorial003.py"
```

Three new things, all on the parameters:

* `Field(description=...)`: a per-argument description the model reads alongside the docstring.
* `Field(ge=1, le=50)`: numeric bounds. They land in the schema as `"minimum": 1, "maximum": 50`.
* `Literal["fiction", "non-fiction", "poetry"]`: an enum. The model can only pick one of those.

!!! check
    Constraints are not decoration. Call the tool with `limit=999` and the SDK answers with a
    tool error **before your function runs**:

    ```text
    Input should be less than or equal to 50
    ```

    That error goes back to the model as the tool result, and the model reads it and retries with
    a valid value. You wrote `le=50` once and got self-correcting agents for free.

!!! info
    If you've used FastAPI or Pydantic, you already know all of this. It's the same `Field`,
    the same `Annotated`, the same validation. There is nothing MCP-specific to learn here.

## A model as a parameter

When a tool takes more than a couple of arguments, group them into a Pydantic model:

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/tools/tutorial004.py"
```

The `Book` schema is nested inside the tool's input schema (as a `$defs` reference), the model fills it in as a JSON object, and your function receives a **real `Book` instance**, already validated, with `.title`, `.author` and `.year` attributes.

You can mix and match: plain parameters next to model parameters, nested models, lists of models. It's Pydantic all the way down.

## `async def`

If a tool does I/O (calls an API, reads a file, queries a database), declare it `async def` and `await` inside it. The SDK awaits it.

A plain `def` tool works too: the SDK runs it in a thread so it never blocks the server.

There is nothing else to configure.

## Names, titles, and annotations

Everything the SDK infers, you can override in the decorator:

```python title="server.py" hl_lines="8-11"
--8<-- "docs_src/tools/tutorial005.py"
```

* `title` is a human-readable name for UIs. Clients show *"Search the catalog"* instead of `search_books`.
* `annotations` are behavioural **hints** for the client:
  * `read_only_hint=True`: this tool doesn't change anything.
  * `open_world_hint=False`: it works on a closed set of things (this catalog), not the open web.
  * The other two, `destructive_hint` and `idempotent_hint`, describe a tool that *writes*: may it
    delete something, and is calling it twice the same as calling it once? The spec defines both
    only for non-read-only tools, so they would say nothing on `search_books`.

A well-behaved client uses them to decide things like *"do I need to ask the user before running this?"*. They are hints, not security. Never rely on a client honouring them.

!!! tip
    `name=` and `description=` are also accepted by `@mcp.tool()` if you don't want to derive them
    from the function name and docstring. Most of the time you do.

## Recap

* `@mcp.tool()` on a function makes it a tool. Name from the function, description from the docstring.
* Type hints **are** the input schema. Defaults make arguments optional.
* `Annotated[..., Field(...)]` adds descriptions and constraints; `Literal` adds enums.
* A Pydantic model parameter is how you take a structured "body".
* Bad arguments are rejected for you, with an error the model can read and recover from.
* `async def` for I/O, plain `def` for everything else.

Next up, **[Structured Output](structured-output.md)**: what happens to the value you `return`.
