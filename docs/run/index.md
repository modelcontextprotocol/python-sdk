# Running your server

`mcp.run()` starts the server.

The only decision you make is the **transport**: how the bytes between your server and its client actually move.

## Pick a transport

| Transport | What it is | When |
|---|---|---|
| `stdio` | The host launches your file as a subprocess and speaks over its stdin and stdout. | Local servers. The default. |
| `streamable-http` | A real HTTP server listening on a port. | Anything you deploy. |
| `sse` | The older HTTP transport. | You don't. |

!!! warning
    SSE was superseded by Streamable HTTP in the 2025-03-26 protocol revision.
    `mcp.run(transport="sse")` still works, with its own `sse_path=` and `message_path=`
    options, but it exists for clients that haven't moved. Don't build anything new on it.

## `mcp.run()`

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/run/tutorial001.py"
```

* `run()` is synchronous. It blocks for the life of the server.
* With no argument, the transport is `stdio`.
* It sits under `if __name__ == "__main__":` because everything that loads your server (`mcp dev`, `mcp run`, `mcp install`, your tests) **imports** this file. The guard keeps an import from turning into a running server.

### stdio

There is nothing to configure. The host starts your file as a child process, writes requests to its stdin, and reads responses from its stdout.

Run it yourself and you see the consequence:

```console
python server.py
```

Nothing prints, and it doesn't return. It is waiting on stdin for a host to speak first.

That also means stdout **is the wire**. A stray `print()` corrupts the stream; the `logging` module writes to stderr and is the right tool. That story is in **[Logging](../tutorial/logging.md)**.

### Try it

```console
uv run mcp dev server.py
```

The Inspector does exactly what a real host does: it launches `server.py` as a subprocess and connects to it over stdio.

You never gave it a port. There isn't one.

## Streamable HTTP

To put the same server on a port instead, name the transport (and its options) in `run()`:

```python title="server.py" hl_lines="13"
--8<-- "docs_src/run/tutorial002.py"
```

That one line builds a Starlette app and serves it with uvicorn. Clients connect to `http://127.0.0.1:3001/mcp`.

Each transport has its own keyword arguments, all on `run()`:

* `host` / `port`: where to listen. Defaults `127.0.0.1` and `8000`.
* `streamable_http_path`: where the MCP endpoint lives. Default `/mcp`.
* `json_response=True`: answer with plain JSON instead of an SSE stream.
* `stateless_http=True`: a fresh transport per request, no session tracking.
* `event_store`, `retry_interval`, `transport_security`: resumability and DNS-rebinding protection. They can wait, until you deploy somewhere other than localhost; **[Add to an existing app](asgi.md)** covers `transport_security`.

!!! warning
    Transport options go to `run()`, **not** to `MCPServer(...)`. The constructor describes what
    your server *is*: name, version, instructions. `run()` describes how it is served. Get it
    backwards and Python answers before MCP is even involved:

    ```text
    TypeError: MCPServer.__init__() got an unexpected keyword argument 'port'
    ```

`run()` is the short road. The moment you need more (your server mounted inside an existing app, two servers in one process, CORS for browser clients), you build the ASGI app yourself and hand it to any ASGI host. That is **[Add to an existing app](asgi.md)**.

## Server settings

A couple of things about running are not about the transport. They are constructor arguments:

```python title="server.py" hl_lines="3"
--8<-- "docs_src/run/tutorial003.py"
```

* `log_level`: handed to `logging.basicConfig()` the moment `MCPServer(...)` is constructed. That configures the **root** logger, so it sets the level for your own loggers too, not just the SDK's. Default `"INFO"`.
* `debug`: forwarded to the Starlette app that the HTTP transports build. Default `False`.

Both land on `mcp.settings`, which you can read back at runtime.

## The `mcp` command

The `[cli]` extra installs a small command-line tool around all of this.

`mcp dev` runs your server under the **MCP Inspector**:

```console
uv run mcp dev server.py
uv run mcp dev server.py --with pandas --with numpy
uv run mcp dev server.py --with-editable .
```

`--with` adds packages to the environment it builds; `--with-editable` installs your own package into it. It needs `npx` on your `PATH`: the Inspector is a Node.js app.

`mcp run` imports the file, finds the server object (a module-level `mcp`, `server`, or `app`), and calls `run()` on it:

```console
uv run mcp run server.py
uv run mcp run server.py:bookshop
```

The `:` suffix names the object when it isn't called `mcp`, `server`, or `app`.

Your `if __name__ == "__main__":` block never executes here: `mcp run` calls `run()` itself, and the only option it forwards is `--transport`.

`mcp install` registers the server with **Claude Desktop**, so the app launches it for you:

```console
uv run mcp install server.py --name "Bookshop"
uv run mcp install server.py -v API_KEY=abc123 -f .env
```

`-v KEY=VALUE` and `-f .env` record environment variables in that entry. Claude Desktop starts your server in its own process. Your shell's environment is not there.

`mcp version` prints the installed SDK version.

!!! tip
    `mcp dev` and `mcp run` only understand `MCPServer`. If you build with the low-level `Server`,
    you run it yourself. See **[The low-level Server](../advanced/low-level-server.md)**.

## Recap

* A **transport** is how bytes reach your server: `stdio` for a local subprocess, `streamable-http` for a port. SSE is superseded.
* `mcp.run()` picks the transport. With no argument it is `stdio`, and it blocks.
* Every transport option (`host`, `port`, `streamable_http_path`, ...) is an argument to `run()`, never to `MCPServer(...)`.
* Keep `run()` under `if __name__ == "__main__":`. Everything that loads your server imports the file first.
* `log_level=` and `debug=` are constructor arguments; they land on `mcp.settings`.
* `mcp dev` for the Inspector, `mcp run` to execute a file, `mcp install` for Claude Desktop, `mcp version` for the version.
* The transport never changes what your server *is*: all three files on this page expose the identical tool.

When `run()` itself is the limit (your server inside an app that already exists), the next step is **[Add to an existing app](asgi.md)**.
