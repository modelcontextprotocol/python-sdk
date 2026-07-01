# Logging

Log from a tool the way you log from any other Python function: with the standard library.

MCP has a protocol-level **logging capability**: a server could push its log messages to the client as notifications, through methods on the `Context` object. The 2026-07-28 revision of the spec **deprecates that capability and does not replace it**, so these docs don't teach it. The full list of what's deprecated and what to do instead is in **[Deprecated features](../deprecated.md)**.

What you do instead is what you do in every other Python program: the standard library.

## A tool that logs

```python title="server.py" hl_lines="1 5 13"
--8<-- "docs_src/logging/tutorial001.py"
```

* `logging.getLogger(__name__)` gives you a logger named after your module. Create it once, at the top.
* Inside the tool you call `logger.info(...)` like in any other function. Nothing to inject, nothing to `await`, nothing MCP-specific.

!!! check
    Call the tool and look at the whole result:

    ```python
    result.content             # [TextContent(text="Found 3 books matching 'dune'.")]
    result.structured_content  # {'result': "Found 3 books matching 'dune'."}
    ```

    The log line is nowhere in it. Logging is for **you**, the person operating the server. The model
    never sees it. If the model should read something, `return` it.

## Where it goes

For a **stdio** server this question matters more than usual. The host launched your server as a subprocess and is reading MCP messages from its **stdout**. Standard error is yours.

The standard library already does the right thing: log output goes to `sys.stderr` by default. Your `logger.info(...)` lines land in the terminal (or wherever the host collects the subprocess's stderr), and the protocol stream stays clean.

!!! tip
    Never `print()` in a stdio server. `print` writes to **stdout**, and stdout *is* the wire: one stray
    line and the client is trying to parse it as JSON-RPC.

    `logger.debug("got here")` is the same one line of effort and goes to the right place.

## The level

You don't have to call `logging.basicConfig()` yourself. Constructing an `MCPServer` already did, with a handler pointed at standard error, at the level you pass as `log_level=`, so `MCPServer("Bookshop", log_level="DEBUG")` is all it takes to see your `logger.debug(...)` lines.

The default is `"INFO"`.

`logging.basicConfig()` never replaces handlers that already exist. If you configure logging yourself before creating the server, your configuration wins.

## Try it

Run the server with the MCP Inspector:

```console
uv run mcp dev server.py
```

Call `search_books` from the **Tools** tab. The Inspector shows you the result: only the return value. The line

```text
Searching for 'dune'
```

went to standard error: the terminal, not the wire.

!!! info
    If what you actually want is *tracing* (every request, how long it took, whether it failed), you
    don't want log lines, you want spans. Your server already emits them: the SDK traces every
    message with OpenTelemetry out of the box. See **[OpenTelemetry](../run/opentelemetry.md)**.

## Recap

* The MCP protocol's logging capability is deprecated by the 2026-07-28 spec and not replaced. Don't build on it.
* `logger = logging.getLogger(__name__)` at module level, `logger.info(...)` in the tool. That's the whole pattern.
* Log output never reaches the model. Only the value you `return` does.
* Standard error is yours; stdout belongs to the protocol. Never `print()` in a stdio server.
* `MCPServer(..., log_level="DEBUG")` sets the level, and a logging configuration you made first is left alone.

Next: telling connected clients that something on your server changed — the tool list, a resource — with **[Subscriptions](subscriptions.md)**.
