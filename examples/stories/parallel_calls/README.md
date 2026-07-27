# parallel-calls

Two `Client`s connected to the same server, each with a `call_tool` in flight
at once. The `meet` tool is a rendezvous: a handler signals its own arrival,
then blocks until every named peer has arrived too — so neither call can return
unless the server runs both handlers concurrently. Each caller's
`progress_callback=` sees only the notifications for *its* request — each
`Client` is a separate connection, so there's no shared wire for them to cross
on.

## Run it

The tested legs run in-memory (`Client(server)`); the identical `main` body
works unchanged over HTTP — both clients just reach the same server. Under
`--http` the client self-hosts that server on a free port, runs, then tears it
down:

```bash
# --legacy because handler-emitted progress is dropped on the modern
# streamable-HTTP path today (see Caveats).
uv run python -m stories.parallel_calls.client --http --legacy
# same, against the lowlevel-API server variant
uv run python -m stories.parallel_calls.client --http --legacy --server server_lowlevel
```

There is no stdio run for this story: the stdio default spawns a fresh server
subprocess per connection, so two clients there could never rendezvous.

## What to look at

- **`client.py` — the two visible `Client(targets(), mode=...)` blocks.** Each
  connection is constructed inside `attend(...)`; `targets()` yields a fresh
  target on every call and both land on the same server instance. The two
  blocks run in one `anyio` task group.
- **`server.py` — the `arrivals` barrier.** Each handler sets its own
  `anyio.Event` then waits for every peer's. A server that processed requests
  sequentially would never set the second event, so the client would time out —
  the timeout *is* the concurrency assertion. No sleeps.
- **`client.py` — `progress_callback=` per call.** Each call passes its own
  callback; `received == {"a": ["a"], "b": ["b"]}` shows each connection
  delivered its own progress, and — combined with the rendezvous — that both
  calls were genuinely in flight at once.
- **`server_lowlevel.py`** — same wire contract on the lowlevel `Server`,
  reporting via `ctx.session.report_progress(...)`.

## Caveats

- Over Streamable HTTP in the modern (2026-07-28) era, handler-emitted progress
  is currently dropped (the single-exchange dispatch context no-ops `notify()`).
  In-memory (both eras) and legacy-era HTTP deliver progress correctly — hence
  the `--legacy` above.

## Spec

[Progress flow](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/progress)

## See also

`streaming/` (progress + cancellation on one call), `reconnect/` (the other
multi-connection client), `tools/` (basics).
