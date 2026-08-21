# Deprecated features

The 2026-07-28 spec retires five things. The SDK still implements every one of them, and every one of them now carries a **deprecation warning**. One SDK helper is deprecated on its own account and is listed [at the end](#deprecated-sdk-helpers).

The table below names each deprecated feature, why it is going away, and the replacement to build on.

## What is deprecated

| Deprecated | Why | What you do instead |
|---|---|---|
| **Roots**: `ctx.session.list_roots()`, `client.send_roots_list_changed()`, the `list_roots_callback=` you pass to `Client(...)` | [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) retires the capability. | Take the paths as ordinary tool arguments or resource URIs, or embed a `ListRootsRequest` in an `InputRequiredResult` (see **[Multi-round-trip requests](handlers/multi-round-trip.md)**). |
| **Server-initiated sampling**: `ctx.session.create_message()`, the `sampling_callback=` you pass to `Client(...)` | SEP-2577 retires the capability. | Return `InputRequiredResult` and let the client retry the call (see **[Multi-round-trip requests](handlers/multi-round-trip.md)**). |
| **Protocol logging**: `ctx.log()`, `ctx.debug()`, `ctx.info()`, `ctx.warning()`, `ctx.error()`, `ctx.session.send_log_message()`, `client.set_logging_level()` | SEP-2577 retires the capability. Nothing in-protocol replaces it. | Ordinary `import logging` to stderr (see **[Logging](handlers/logging.md)**). |
| **`ping`**: `client.send_ping()` | **Removed** from the protocol, not merely deprecated. There is no `ping` method in 2026-07-28. | Nothing. It only works against a `mode="legacy"` connection. |
| **Client->server progress**: `client.send_progress_notification()` | 2026-07-28 makes progress server->client only. | Nothing to send. Your *server* reports progress with `ctx.report_progress()` (see **[Progress](handlers/progress.md)**). |

Three things fall out of that table:

* Roots, sampling, and logging go together. One proposal, **SEP-2577**, deprecates all three capabilities at once.
* Sampling and roots share a deeper problem: they are places a **server** sends a **request** to the **client**. That whole direction is what 2026-07-28 replaces with **[Multi-round-trip requests](handlers/multi-round-trip.md)**. It is the standalone RPC methods (`sampling/createMessage`, `roots/list`, and push-style `elicitation/create`) that are gone; the `CreateMessageRequest` / `ListRootsRequest` / `ElicitRequest` payload types survive, embedded in `InputRequiredResult.input_requests`, and on the client they hit the same callbacks.
* `ping` is the odd one out. The protocol does not deprecate it, it removes it. The SDK method still warns (its message says *removed*, not *deprecated*) and calling it on a modern connection answers with *"Method not found"*.

## Deprecated is advisory

Nothing breaks today.

Every method above keeps working against any session that negotiated **2025-11-25 or earlier**. Pin `mode="legacy"` on the client and you get exactly the pre-2026 behaviour. There are no wire changes and capability negotiation is unchanged.

What changes is that you get a visible warning the first time each one runs:

```text
MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
```

`MCPDeprecationWarning` subclasses `UserWarning`, **not** `DeprecationWarning`. That is deliberate: Python's default filter only shows `DeprecationWarning` in code run directly as `__main__`, which is how libraries deprecate things and nobody notices for two years. This one shows up everywhere, with no `-W` flag.

!!! warning
    "Advisory" stops at the wire. Sampling and roots are server-to-client *requests*, and a
    2026-07-28 session has no channel to carry one. Call `ctx.session.create_message()`
    inside a tool on a modern connection and the warning still fires, and then the send
    fails with an error:

    ```text
    Cannot send 'sampling/createMessage': this transport context has no back-channel
    for server-initiated requests.
    ```

    Two signals, in that order. The `MCPDeprecationWarning` fires the moment you call the
    method, on any connection. The error is what comes back when the SDK then tries to
    send. These two only work end-to-end on a `mode="legacy"` connection whose client
    registered the matching callback.

## `ping` on a legacy session

A **ping** is an empty request either side can send to check that the other is still answering. The 2026-07-28 spec removes it ([SEP-2575](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2575)): every request a modern client sends already proves the server is there, and a modern server has no channel to send one. Both SDK methods still work on a handshake-era session. From the client:

```python
async def main() -> None:
    async with Client("http://localhost:8000/mcp", mode="legacy") as client:
        await client.send_ping()  # warns; returns an EmptyResult
```

And from the server, inside any handler:

```python
@mcp.tool()
async def check_client(ctx: Context) -> str:
    """A tool that still pings the client mid-call."""
    await ctx.session.send_ping()  # no warning; an EmptyResult while the client is connected
    return "client answered"
```

* `client.send_ping()` warns with `MCPDeprecationWarning` on every call. On a default (`2026-07-28`) connection the server answers `MCPError: Method not found` instead.
* `ctx.session.send_ping()` carries no warning. On a modern connection it raises the same no-back-channel error as any other server-initiated request.
* Neither side registers anything to answer a ping.

## Roots change notifications

A 2025-era client that declared the roots capability can tell the server that its workspace folders changed by sending `notifications/roots/list_changed`; the server responds by requesting `roots/list` again. The 2026-07-28 spec removes the notification along with the rest of the push-style roots flow. On the client, passing `list_roots_callback=` (**[Client callbacks](client/callbacks.md)**) is what declares `"roots": {"listChanged": true}`, and one call keeps that promise:

```python
async def open_folder(client: Client, uri: str, name: str) -> None:
    """The user opened another folder: expose it through the roots callback, then tell the server."""
    workspace.append(Root(uri=FileUrl(uri), name=name))
    await client.send_roots_list_changed()
```

On the server, the low-level `Server` takes the receiving handler:

```python
async def roots_changed(ctx: ServerRequestContext, params: NotificationParams | None) -> None:
    """The client's roots changed: ask for the new list."""
    roots = (await ctx.session.list_roots()).roots


server = Server("Bookshop", on_roots_list_changed=roots_changed)
```

* `workspace` is the list your `list_roots_callback` returns. `client.send_roots_list_changed()` warns, and it needs a `mode="legacy"` client: on a modern connection the notification is silently dropped. Keep the session open afterwards, because the server's follow-up `roots/list` arrives on it.
* `MCPServer` has no hook for the notification. On the low-level `Server`, `on_roots_list_changed=` registers the handler (deprecated too, and it warns at construction). The notification carries no payload, so the handler calls `ctx.session.list_roots()` for the new list.

## Silencing the warning

Don't, in new code.

But a server you maintain that genuinely serves pre-2026 clients has every right to a quiet log. Filter the category before the first deprecated call runs:

```python
import warnings

from mcp import MCPDeprecationWarning

warnings.filterwarnings("ignore", category=MCPDeprecationWarning)
```

That is the whole API. There is no per-method switch, and you don't want one: the point of one category is that one line silences it and one line brings it back.

!!! check
    Run the filter the other way and you get a free regression test. Add
    `"error::mcp.MCPDeprecationWarning"` to the `filterwarnings` setting in your pytest
    configuration and the deprecated call **raises** instead of warning. A tool named
    `old_log` that still calls `ctx.info()` stops passing: the call comes back `is_error=True` with
    `Error executing tool old_log`, and the captured server log names the culprit:

    ```text
    mcp.shared.exceptions.MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
    ```

    One line of pytest configuration, and a deprecated call can never sneak back into your
    codebase without failing a test.

## Deprecated SDK helpers

These are not spec changes, only SDK internals with a better replacement. They warn with the same `MCPDeprecationWarning` and will be removed in 3.0.

| Deprecated | What you do instead |
|---|---|
| `FuncMetadata.call_fn_with_arg_validation()` | `FuncMetadata.validate_arguments()` and then `FuncMetadata.call_fn()`. Only code that drives `FuncMetadata` directly (a custom `Tool` subclass, say) ever called it. |

## Recap

* The 2026-07-28 spec deprecates **roots**, server-initiated **sampling**, and protocol **logging** (all [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)), restricts **progress** to server-to-client, and removes **`ping`**.
* The replacement column points you onward: **[Multi-round-trip requests](handlers/multi-round-trip.md)** for sampling and roots, **[Logging](handlers/logging.md)** for logging, **[Progress](handlers/progress.md)** for progress. `ping` needs nothing at all.
* Deprecated is advisory: no wire changes, everything keeps working against pre-2026 sessions, and you get a visible `MCPDeprecationWarning` (a `UserWarning`, so it is on by default).
* Sampling and roots additionally need a back-channel that a 2026-07-28 session does not have. On a modern connection they warn and then they raise.
* `warnings.filterwarnings("ignore", category=MCPDeprecationWarning)` silences the whole category; `"error::mcp.MCPDeprecationWarning"` in pytest turns it into a test failure.
* One SDK helper, `FuncMetadata.call_fn_with_arg_validation()`, is deprecated separately for removal in 3.0.
* New code should not be built on any of these.

Every other page in these docs teaches the current API.
