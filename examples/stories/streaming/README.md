# streaming

The three in-flight server→client channels during a tool call: **progress**
(`ctx.report_progress` → the caller's `progress_callback=`), **logging**
(`notifications/message` → the client's `logging_callback=`), and
**cancellation** (abandoning the client's awaiting scope interrupts the server
handler). One `countdown(steps)` tool emits a progress notification and a log
line per step; the client asserts both streams arrive in order, then cancels a
long call mid-flight by cancelling the enclosing `anyio.CancelScope` from
inside the progress callback (event-driven, no `sleep`).

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.streaming.client
uv run python -m stories.streaming.client --server server_lowlevel

# HTTP — the client self-hosts the server on a free port, runs, then tears it
# down
uv run python -m stories.streaming.client --http
# same, against the lowlevel-API server variant
uv run python -m stories.streaming.client --http --server server_lowlevel
```

## What to look at

- `client.py` `main` — opens with `async with Client(target, mode=mode,
  logging_callback=on_log)`. The story owns that construction; the harness only
  picks the target and era. `logging_callback` is constructor-only on `Client`
  (no setter after connect), so the callback and the `logs` list it fills are
  closed over right above the `Client(...)` call.
- `server.py` — `ctx.report_progress(i, steps, msg)` is a silent no-op when the
  caller passed no `progress_callback`; the SDK reads the token from the
  request's `_meta` for you. The log notification is sent via the raw
  `session.send_notification(...)` because the `ctx.log()` / `ctx.info()`
  shorthands are deprecated (SEP-2577) with no non-deprecated replacement yet.
  `related_request_id=` keeps the log on this request's response stream — over
  streamable HTTP an unrelated notification would ride the standalone GET
  stream instead.
- `server.py` — `ctx.request_context.session` / `ctx.request_context.request_id`
  is the interim 2-hop path; a later release will shorten these.
- `server.py` — the `except anyio.get_cancelled_exc_class(): raise` block is
  where a real handler would release resources before re-raising. **Never
  swallow** the cancellation exception.
- `client.py` — cancellation is just cancelling the `anyio` scope around
  `await client.call_tool(...)`; the SDK sends `notifications/cancelled` for
  you on stateful transports. There is no `client.cancel(request_id)` API.
- `server_lowlevel.py` — the same wire contract built by hand against
  `ServerRequestContext.session` directly.

## Caveats

- **Logging is deprecated** in the 2026-07-28 protocol (SEP-2577); functional
  through the deprecation window. Migration: write to stderr or emit
  OpenTelemetry instead of `notifications/message`. It is shown here because
  servers still need to support 2025-era clients during that window. Progress
  and cancellation are **not** deprecated. TODO(maxisbey): revisit before beta.
- When a request is cancelled the server currently replies with
  `ErrorData(code=0, message="Request cancelled")`; the spec says it should not
  reply at all. The client never observes it (its awaiting task is already
  cancelled), so this story does not assert on the reply.

## Spec

[Progress](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/progress),
[cancellation](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/cancellation),
[logging](https://modelcontextprotocol.io/specification/2025-11-25/server/utilities/logging)

## See also

`parallel_calls/` (concurrent in-flight calls), `error_handling/` (the
cancellation error path), `tools/` (the basics this builds on).
