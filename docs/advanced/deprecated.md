# Deprecated features

The 2026-07-28 spec retires five things. The SDK still implements every one of them, and every one of them now carries a **deprecation warning**.

The table below names each deprecated feature, why it is going away, and the replacement to build on.

## What is deprecated

| Deprecated | Why | What you do instead |
|---|---|---|
| **Roots**: `ctx.session.list_roots()`, `client.send_roots_list_changed()`, the `list_roots_callback=` you pass to `Client(...)` | [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) retires the capability. | Take the paths as ordinary tool arguments or resource URIs, or embed a `ListRootsRequest` in an `InputRequiredResult` (see **Multi-round-trip requests**). |
| **Server-initiated sampling**: `ctx.session.create_message()`, the `sampling_callback=` you pass to `Client(...)` | SEP-2577 retires the capability. | Return `InputRequiredResult` and let the client retry the call (see **Multi-round-trip requests**). |
| **Protocol logging**: `ctx.log()`, `ctx.debug()`, `ctx.info()`, `ctx.warning()`, `ctx.error()`, `ctx.session.send_log_message()`, `client.set_logging_level()` | SEP-2577 retires the capability. Nothing in-protocol replaces it. | Ordinary `import logging` to stderr (see **Logging**). |
| **`ping`**: `client.send_ping()` | **Removed** from the protocol, not merely deprecated. There is no `ping` method in 2026-07-28. | Nothing. It only works against a `mode="legacy"` connection. |
| **Client->server progress**: `client.send_progress_notification()` | 2026-07-28 makes progress server->client only. | Nothing to send. Your *server* reports progress with `ctx.report_progress()` (see **Progress**). |

Three things fall out of that table:

* Roots, sampling, and logging go together. One proposal, **SEP-2577**, deprecates all three capabilities at once.
* Sampling and roots share a deeper problem: they are places a **server** sends a **request** to the **client**. That whole direction is what 2026-07-28 replaces with **Multi-round-trip requests**. It is the standalone RPC methods (`sampling/createMessage`, `roots/list`, and push-style `elicitation/create`) that are gone; the `CreateMessageRequest` / `ListRootsRequest` / `ElicitRequest` payload types survive, embedded in `InputRequiredResult.input_requests`, and on the client they hit the same callbacks.
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
    `old_log` that still calls `ctx.info()` stops passing and starts reporting:

    ```text
    Error executing tool old_log: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
    ```

    One line of pytest configuration, and a deprecated call can never sneak back into your
    codebase without failing a test.

## Recap

* The 2026-07-28 spec deprecates **roots**, server-initiated **sampling**, and protocol **logging** (all SEP-2577), restricts **progress** to server-to-client, and removes **`ping`**.
* The replacement column points you onward: **Multi-round-trip requests** for sampling and roots, **Logging** for logging, **Progress** for progress. `ping` needs nothing at all.
* Deprecated is advisory: no wire changes, everything keeps working against pre-2026 sessions, and you get a visible `MCPDeprecationWarning` (a `UserWarning`, so it is on by default).
* Sampling and roots additionally need a back-channel that a 2026-07-28 session does not have. On a modern connection they warn and then they raise.
* `warnings.filterwarnings("ignore", category=MCPDeprecationWarning)` silences the whole category; `"error::mcp.MCPDeprecationWarning"` in pytest turns it into a test failure.
* New code should not be built on any of these.

Every other page in these docs teaches the current API.
