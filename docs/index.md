# MCP Python SDK

!!! info "You are viewing the in-development v2 documentation"
    For the current stable release, see the [v1.x documentation](https://py.sdk.modelcontextprotocol.io/).

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
    uv add "mcp[cli]==2.0.0a3"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]==2.0.0a3"
    ```

The `[cli]` extra gives you the `mcp` command; you'll want it for development.

!!! warning "Pin the version while v2 is in alpha"
    Installers never select a pre-release unless you name one, so an unpinned `uv add "mcp[cli]"`
    gives you the latest **v1.x** release, which this documentation does not describe. Check
    [PyPI](https://pypi.org/project/mcp/#history) for the newest alpha before you copy the line
    above. See [Installation](installation.md) for the details.

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

* The **[Tutorial](tutorial/index.md)** walks through everything a server can do, one small step at a time.
* Migrating from v1? Start with the **[Migration Guide](migration.md)**.
* Hunting for an exact signature? The **[API Reference](api/mcp/index.md)** is generated from the source.
