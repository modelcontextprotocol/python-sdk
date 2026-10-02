# Cancellation

A client can give up on a call: the user pressed stop, or a timeout ran out.

When it does, the SDK **cancels your handler**. The `await` it is waiting on raises, the function unwinds, and nothing it returns is sent. Most handlers need to do nothing about that.

Two kinds do: a handler with something to clean up, and a handler that is a plain `def`.

## Clean up in an `async def` tool

Put the cleanup in a `finally`:

```python title="server.py" hl_lines="23 26-28"
--8<-- "docs_src/cancellation/tutorial001.py"
```

* The `finally` runs however the tool ends: it returned, it raised, or it was cancelled.
* Cleanup that has to `await` needs `shield=True`. In a cancelled handler every further `await` raises too, so without the shield `release_hold` would stop at its first line.
* Nothing can cancel a shielded block, so give it a time limit. Here that is `5` seconds.

!!! tip
    Reach for `finally`, not `except`. The cancellation has to keep travelling up once your cleanup
    is done, and a `finally` lets it.

## Stop early in a plain `def` tool

A plain `def` tool runs in a thread, and nothing can interrupt a thread from outside. The tool has to ask:

```python title="server.py" hl_lines="18"
--8<-- "docs_src/cancellation/tutorial002.py"
```

* `anyio.from_thread.check_cancelled()` does nothing while the call is live, and raises once it has been cancelled. Call it between units of work.
* A `def` tool that never asks runs to the end, and its result is thrown away.

## Where it applies

Prompt and resource functions are cancelled exactly like tools.

It works the same over stdio and Streamable HTTP. With this SDK's `Client`, giving up means cancelling the task that awaits `call_tool`, or letting its `read_timeout_seconds` run out.

!!! warning
    Two Streamable HTTP options keep the news from your handler: `json_response=True` on a
    `2026-07-28` connection, and `stateless_http=True` on a legacy one. There the handler runs to
    the end whatever the client did.

## Recap

* When the client gives up on a call, the SDK cancels the handler: tool, prompt or resource.
* `async def`: clean up in a `finally`, and put cleanup that awaits inside `anyio.move_on_after(seconds, shield=True)`.
* Plain `def`: call `anyio.from_thread.check_cancelled()` between units of work, or the tool runs to the end.
* `json_response=True` (modern connections) and `stateless_http=True` (legacy ones) switch cancellation off.

Progress and cancellation are between a running tool and its *caller*. The lines it logs for *you*, the person operating the server, are a different channel: **[Logging](logging.md)**.
