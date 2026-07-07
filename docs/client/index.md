# The Client

A **`Client`** is how a Python program talks to an MCP server.

It is one object with one lifecycle: construct it, enter `async with`, call methods. Every protocol verb (list the tools, call one, read a resource, render a prompt) is an `async` method on it that returns a typed result.

## Your first client

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

The server at the top is only there so you have something to connect to. The client is the five highlighted lines.

* `Client(mcp)` is given the **server object itself**. That is the in-memory transport: no subprocess, no port, no HTTP. It is how every example on this page, and every test you write, connects.
* `async with` is the **lifecycle**. Entering it connects and negotiates; leaving it disconnects. There is no `connect()` / `close()` pair, and a `Client` cannot be reused after the block ends.
* Inside the block the connection facts are already there as plain properties.

### What you can pass to `Client`

`Client` takes one positional argument and resolves the transport from its type:

* An `MCPServer` (or low-level `Server`) instance: connected **in-process**.
* A URL string (`Client("http://localhost:8000/mcp")`): Streamable HTTP, the production path.
* A **transport**: anything you can `async with ... as (read, write)`, such as `stdio_client(...)` wrapping a subprocess.

Everything else on this page is identical across all three. Headers, subprocesses, timeouts, and the `Transport` protocol get their own page: **[Client transports](transports.md)**.

### What's on a connected client

Four read-only properties, populated the moment you enter the block:

* `client.server_info`: the server's identity. `server_info.name` here is `"Bookshop"`, `server_info.version` is whatever the server reports.
* `client.server_capabilities`: what the server can do (`tools`, `resources`, `prompts`, `completions`, ...). A capability the server doesn't have is `None`.
* `client.protocol_version`: the protocol version the two sides agreed on. Here it is `"2026-07-28"`.
* `client.instructions`: the server's `instructions=` string, or `None` if it didn't set one.

You never picked a protocol version. By default the `Client` probes the server and falls back to the classic handshake on older ones, so one client works against any era of server. When you need to control that, **[Protocol versions](../protocol-versions.md)** has the whole story.

!!! tip
    `client.session` is the underlying `ClientSession`, the low-level escape hatch.
    You won't need it for anything on this page.

## Listing tools

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial002.py"
```

`list_tools()` returns a `ListToolsResult`; the tools are in `.tools`. Each one is the complete definition a host would hand to a model:

```python
tool.name          # 'search_books'
tool.title         # 'Search the catalog'
tool.description   # 'Search the catalog by title or author.'
```

and `tool.input_schema` is the JSON Schema the server derived from the function's type hints:

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

That schema is everything a UI needs to render an argument form, and everything a model needs to produce valid arguments.

!!! tip
    `title` is optional, so a UI showing tools to a human has to pick: the `title` if there is one,
    the `name` if not. `from mcp.shared.metadata_utils import get_display_name` does exactly that,
    for tools, resources, resource templates and prompts.

## Calling a tool

`call_tool(name, arguments)` runs the tool and gives you back a `CallToolResult`.

```python title="client.py" hl_lines="26-33"
--8<-- "docs_src/client/tutorial003.py"
```

The server's `lookup_book` returns a Pydantic `Book`. Here is what the client sees:

```python
result.content             # [TextContent(type='text', text='{\n  "title": "Dune",\n  "author": "Frank Herbert",\n  "year": 1965\n}')]
result.structured_content  # {'title': 'Dune', 'author': 'Frank Herbert', 'year': 1965}
result.is_error            # False
```

One return value, three things to read. Each has a different consumer.

### `content`: what the model reads

`content` is a `list` of **content blocks**, and a content block is a union: `TextContent`, `ImageContent`, `AudioContent`, `ResourceLink`, or `EmbeddedResource`. A tool can return several, of different kinds.

That is why `main` narrows with `isinstance(block, TextContent)` before touching `block.text`. Notice there is no `.text` outside the `isinstance`: the type checker won't allow it, because `ImageContent` has `.data`, not `.text`. The union is honest about what a tool is allowed to send you; your code should be too.

### `structured_content`: what your application reads

`structured_content` is the tool's return value as JSON, matching the tool's declared `output_schema`. No string parsing, no guessing.

When both are present they say the same thing twice on purpose: `content` is for a model, `structured_content` is for code. Where the structured half comes from, and how to control it, is the **[Structured Output](../servers/structured-output.md)** page.

### `is_error`: whether the tool failed

A tool that raises does **not** raise in your client. It comes back as an ordinary result with `is_error=True`.

!!! check
    Ask `lookup_book` for `"Solaris"` (a title that isn't in the catalog) and the function raises
    `ValueError`. The call still returns normally:

    ```python
    result.is_error            # True
    result.content             # [TextContent(type='text', text="Error executing tool lookup_book: No book titled 'Solaris' in the catalog.")]
    result.structured_content  # None
    ```

    The exception's message landed in `content`, where the **model** can read it and try again. That
    is deliberate: a tool error is part of the conversation, not a crash. Always look at `is_error`
    before you trust `structured_content`.

!!! warning
    `is_error=True` covers more than your own `raise`. Ask for a tool the server doesn't even have
    (`call_tool("does_not_exist", {})`) and nothing raises. You get the same shape back,
    `is_error=True` with `Unknown tool: does_not_exist` in `content`. A `Client` method raises
    `MCPError` only when the server answers with a JSON-RPC **error** instead of a result, and
    **[Handling errors](../servers/handling-errors.md)** covers when a server produces which.

## Resources

The resource verbs come in pairs: two ways to list, one way to read.

```python title="client.py" hl_lines="23-32"
--8<-- "docs_src/client/tutorial004.py"
```

* `list_resources()` returns the **concrete** resources, the ones with a fixed URI. Here: `['catalog://genres']`.
* `list_resource_templates()` returns the **parameterised** ones. Here: `['catalog://genres/{genre}']`. They are two different lists because a template isn't readable until you fill it in.
* `read_resource(uri)` takes a plain `str` URI and works on both: pass `"catalog://genres/poetry"` and the server matches it to the template.

`read_resource` returns `contents`, a list of `TextResourceContents` or `BlobResourceContents`. Same idea as tool content: narrow with `isinstance`, then read `.text` (or `.blob`).

A client can also be told when a resource changes. On 2025-era connections that is `subscribe_resource(uri)` / `unsubscribe_resource(uri)` - a method pair `MCPServer` doesn't implement, so on the 2026-07-28 wire (where those verbs no longer exist) the request answers `-32601`, *Method not found*. The 2026 replacement is a `subscriptions/listen` stream, which `MCPServer` *does* serve - `server_capabilities.resources.subscribe` is `True` there, and **[Subscriptions](../handlers/subscriptions.md)** tells both sides of the story - the client end is [`client.listen(...)`](../handlers/subscriptions.md#watching-the-stream).

## Prompts

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial005.py"
```

`list_prompts()` tells you what the server offers and what each prompt needs:

```python
prompt.name        # 'recommend'
prompt.title       # 'Recommend a book'
prompt.arguments   # [PromptArgument(name='genre', required=True)]
```

`get_prompt(name, arguments)` renders it. The arguments dict is `str -> str`: prompt arguments are always strings. The result is `messages`, a list of `PromptMessage`, each with a `role` and a `content` block:

```python
message.role     # 'user'
message.content  # TextContent(type='text', text='Recommend one poetry book from the catalog and say why.')
```

A host hands those messages straight to the model. That is the whole feature.

## Completions

A server with a completion handler can autocomplete prompt and resource-template arguments as the user types.

```python title="client.py" hl_lines="28-32"
--8<-- "docs_src/client/tutorial006.py"
```

* `ref` says *which* prompt or template you're filling in: a `PromptReference` or a `ResourceTemplateReference`.
* `argument` is `{"name": ..., "value": ...}`: the argument and what the user has typed so far.

The answer is in `result.completion.values`. Type `"p"` and the server comes back with `['poetry']`. The server side, and how a handler uses the *other* already-filled arguments to narrow its suggestions, is the **[Completions](../servers/completions.md)** page.

## Pagination

Every `list_*` method takes a `cursor=` keyword and every result carries a `next_cursor`. When `next_cursor` is `None`, you have everything.

```python title="client.py" hl_lines="23-31"
--8<-- "docs_src/client/tutorial007.py"
```

This loop is correct against every server. `MCPServer` returns everything in one page, so `next_cursor` is `None` and the loop runs once, which is why most code never writes it. Servers that genuinely page, and the rules cursors obey, are in **[Pagination](../advanced/pagination.md)**.

## In tests

`Client(mcp)` with no process and no port is already a test harness for your server.

There is one constructor flag built for that: `Client(mcp, raise_exceptions=True)`. It only has an effect on in-memory connections, and **[Testing](../get-started/testing.md)** is the page that explains it and builds the whole pattern around it.

## Recap

* `Client(x)` connects in-memory to a server object, over Streamable HTTP to a URL string, and over anything else via a transport.
* `async with` is the whole lifecycle. Inside it, `server_info`, `server_capabilities`, `protocol_version` and `instructions` are already populated.
* `list_tools()` gives you each tool's `name`, `title`, `description` and `input_schema`.
* `call_tool()` returns `content` for the model, `structured_content` for your code, and `is_error`. A raising tool is a result, not an exception.
* `content` is a union of block types; narrow with `isinstance` before reading.
* `list_resources` / `list_resource_templates` / `read_resource`, `list_prompts` / `get_prompt`, and `complete` round out the verbs.
* Every `list_*` takes `cursor=`; loop until `next_cursor` is `None`.

The things a server can ask the *client* for, and how you answer them, are **[Client callbacks](callbacks.md)**.
