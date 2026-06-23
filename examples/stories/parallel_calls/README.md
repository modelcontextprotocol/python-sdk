# parallel-calls

One `Client`, two `call_tool` requests in flight at once. Each caller gets its
own answer, and the per-call `progress_callback=` sees only the progress
notifications for *that* request — the SDK demultiplexes by progress token, not
by arrival order.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.parallel_calls.client

# against a running HTTP server
uv run python -m stories.parallel_calls.server --http --port 8000 &
uv run python -m stories.parallel_calls.client --http http://127.0.0.1:8000/mcp
```

## What to look at

- **`server.py` — the `arrivals` barrier.** Each handler sets its own
  `anyio.Event` then waits for every peer's. A server that processed requests
  sequentially would never set the second event, so the client would time out —
  the timeout *is* the concurrency assertion. No sleeps.
- **`client.py` — `progress_callback=` per call.** Two concurrent calls each
  pass a separate callback; `received == {"a": ["a"], "b": ["b"]}` proves the
  SDK routes in-flight progress per request.
- **`server_lowlevel.py`** — same wire contract on the lowlevel `Server`,
  reporting via `ctx.session.report_progress(...)`.

## Caveats

- Over Streamable HTTP in the modern (2026-07-28) era, handler-emitted progress
  is currently dropped (the single-exchange dispatch context no-ops `notify()`).
  That cell is `xfail`; in-memory and legacy-era HTTP both deliver progress
  correctly.
- The N-clients × 1-server variant is omitted: the harness `connect()` factory
  rebuilds the server per call, so a cross-client rendezvous would deadlock.
  Over a long-running HTTP server it works exactly as the single-client case —
  open a second `Client` against the same URL.

## Spec

[Progress flow](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/progress)

## See also

`streaming/` (progress + cancellation on one call), `tools/` (basics).
