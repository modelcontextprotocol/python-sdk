# MCP Python SDK

!!! info "This documents v2, the current stable release line"
    New to v2, or coming from v1? **[What's new in v2](whats-new.md)** is the five-minute tour of what changed, and the **[Migration Guide](migration.md)** covers every breaking change.
    Still on v1.x? Its documentation lives at the [v1.x docs](https://py.sdk.modelcontextprotocol.io/v1/).
    Something rough or confusing? [Tell us](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml).

The **Model Context Protocol (MCP)** lets applications provide context to LLMs in a standardized way, separating the concern of *providing* context from the LLM interaction itself.

This is the official Python SDK for it. With it you can:

* **Build MCP servers** that expose tools, resources, and prompts to any MCP host.
* **Build MCP clients** that connect to any MCP server.
* Speak every standard transport: stdio, Streamable HTTP, and SSE.

## Requirements

Python 3.10+.

## Installation

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

The `[cli]` extra gives you the `mcp` command; you'll want it for development.
See [Installation](get-started/installation.md) for what each dependency is for.

## Example

### Create it

Create a file `server.py`:

```python title="server.py"
--8<-- "docs_src/index/tutorial001.py"
```

That's a complete MCP server.

It exposes one **tool**, `add`, and one templated **resource**, `greeting://{name}`.

### Run it

```console
uv run mcp dev server.py
```

This starts your server and opens the [MCP Inspector](https://github.com/modelcontextprotocol/inspector), an interactive UI for poking at it. Open the URL it prints.

!!! note
    The Inspector is a Node.js app, so `mcp dev` needs `npx` on your `PATH`.

### Try it

In the Inspector, go to **Tools** and call `add` with `a=1`, `b=2`.

You get `3` back. ✨

The Inspector built that form (a required integer field for `a`, another for `b`) from your type hints. So will Claude, and every other MCP host.

Now go to **Resources** and read `greeting://World`:

```text
Hello, World!
```

### Recap

Look again at what you did **not** write:

* No JSON Schema. `a: int, b: int` *is* the schema.
* No request parsing, no serialization, no validation code.
* No protocol handling at all.

You wrote two Python functions with type hints and a docstring. The SDK does the rest.

## Where to go next

* **[Get started](get-started/index.md)** takes you from install to a working, tested server.
* Building an application that *uses* MCP servers? Start with **[Clients](client/index.md)**.
* Already have a FastAPI or Starlette app? **[Add to an existing app](run/asgi.md)** mounts an MCP server inside it.
* Hunting an exact error message? **[Troubleshooting](troubleshooting.md)** is keyed by the verbatim text.
* Wondering what changed in v2? **[What's new in v2](whats-new.md)** is the five-minute tour.
* Migrating from v1? Start with the **[Migration Guide](migration.md)**.
* Hunting for an exact signature? The **[API Reference](api/mcp/index.md)** is generated from the source.
* Reading with an LLM? This documentation is also published in the [llms.txt](https://llmstxt.org/) format:
  [llms.txt](https://py.sdk.modelcontextprotocol.io/llms.txt) is an index of the pages, and
  [llms-full.txt](https://py.sdk.modelcontextprotocol.io/llms-full.txt) contains every page in a single file.
