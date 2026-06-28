# Progress

A tool that takes thirty seconds and says nothing for thirty seconds looks broken.

**Progress notifications** fix that. The tool reports how far along it is; the client decides what to draw with it: a bar, a spinner, a log line.

## Report it from the tool

Take a **`Context`** parameter and call `report_progress`:

```python title="server.py" hl_lines="8 11"
--8<-- "docs_src/progress/tutorial001.py"
```

Three arguments, and you decide what they mean:

* `progress`: how far you are. The spec requires it to **increase** with every report; never repeat a value or go backwards.
* `total`: how much there is in total, if you know. Optional.
* `message`: one human-readable line about *this* step. Optional.

`ctx` is injected because of its type hint and the model never sees it: `import_catalog`'s input schema has a single property, `urls`. **[The Context](context.md)** chapter is all about that object; progress is one of the things it gives you.

## Listen for it from the client

The client opts in **per call**, by passing `progress_callback=` to `call_tool`:

```python title="client.py" hl_lines="7 16"
import anyio
from mcp import Client

from server import mcp


async def show(progress: float, total: float | None, message: str | None) -> None:
    print(f"{message} ({progress}/{total})")


async def main() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "import_catalog",
            {"urls": ["https://example.com/a.json", "https://example.com/b.json"]},
            progress_callback=show,
        )
    print(result.structured_content)


anyio.run(main)
```

The callback is an `async` function taking exactly what the server reported: `progress`, `total`, `message`.

!!! info
    `Client(mcp)` connects straight to the server object, in memory, the same client the **[Testing](testing.md)**
    chapter is built on. `progress_callback` is the same parameter whatever transport the `Client`
    uses; the *timing* you are about to see is the in-memory connection's. It runs your callback
    inline, so every report lands before `call_tool` returns. Over a real transport the
    notifications race the result, and a slow callback can still be running after `call_tool` has
    returned.

### Try it

Put `client.py` next to `server.py` and run it:

```console
python client.py
```

```text
Imported https://example.com/a.json (1/2)
Imported https://example.com/b.json (2/2)
{'result': 'Imported 2 records.'}
```

Every `await ctx.report_progress(...)` on the server became one call to `show` on the client, in order, and both lines printed **before** `call_tool` returned. Progress is not bundled into the result; it streams while the tool is still working.

!!! warning
    `progress_callback` belongs to the **call**, not the `Client`. There is no constructor argument
    for it, because different calls want different callbacks: one drives a download bar, the next
    one a log line.

!!! check
    Now delete `progress_callback=show` and run it again:

    ```text
    {'result': 'Imported 2 records.'}
    ```

    No error, no warning, same result. `report_progress` is a **no-op when the caller didn't ask
    for progress**, so you report unconditionally and never have to wonder whether anyone is
    listening.

## When you don't know the total

`total` is for when you know the denominator. Often you don't: you're draining a feed, walking a cursor, downloading something with no length header.

Leave it out:

```python title="server.py" hl_lines="20"
--8<-- "docs_src/progress/tutorial002.py"
```

The callback receives `total=None`. A client can still show *activity* ("3 imported so far...") but it can't show a percentage. Don't invent a total to get a prettier bar.

!!! tip
    `progress` doesn't have to count anything in particular. Bytes, rows, pages: pick the unit the
    user would recognise, and only promise a `total` you can keep.

## Recap

* `await ctx.report_progress(progress, total=None, message=None)` from any tool that takes a `Context`.
* The client passes `progress_callback=` to `call_tool`: per call, never on the `Client`.
* The callback is `async (progress, total, message) -> None` and fires while the tool is still running.
* No callback on the call means `report_progress` does nothing. Report unconditionally.
* Omit `total` when you don't know it; the callback gets `None`.

Progress is what a running tool shows the *user*. The lines it logs for *you*, the person operating the server, are a different channel: **[Logging](logging.md)** is next.
