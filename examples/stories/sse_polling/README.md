# sse-polling

SEP-1699 server-initiated SSE disconnection with `Last-Event-ID` replay. The
server's `EventStore` stamps every SSE event with an ID and opens each response
stream with a priming event; mid-handler the tool calls
`ctx.close_sse_stream()` to release the open HTTP response (freeing a
connection slot), keeps emitting progress into the event store, and returns.
The client transport sees the stream end, reconnects with `Last-Event-ID`, and
the event store replays everything it missed — `await client.call_tool(...)`
resolves as if the disconnect never happened.

**2025-era only.** `Last-Event-ID` resumability and the sessionful transport
are removed in the 2026-07-28 spec (SEP-2575); there is no modern-era
equivalent.

## Run it

```bash
# in one terminal
uv run python -m stories.sse_polling.server --port 8000
# in another
uv run python -m stories.sse_polling.client --http http://127.0.0.1:8000/mcp --legacy
```

## What to look at

- **`server.py` — `streamable_http_app(event_store=..., retry_interval=0)`.**
  Passing an `EventStore` is what enables resumability: every SSE event gets an
  ID and the response opens with a priming event so the client always has a
  `Last-Event-ID` to reconnect with. `retry_interval=0` makes the client's
  reconnect wait a no-op (the SSE `retry:` hint).
- **`server.py` — `await ctx.close_sse_stream()`.** Ends the current request's
  SSE response without cancelling the handler. Everything emitted afterwards
  goes to the event store and is replayed on reconnect. A no-op when no
  `event_store` is configured.
- **`server_lowlevel.py` — `ctx.close_sse_stream`.** On the lowlevel API the
  callback is an optional field on `ServerRequestContext`; it is `None` unless
  an event store is wired and the negotiated version is in the 2025 era.
- **`client.py` — nothing special.** The `Client` and `streamable_http_client`
  transport handle the priming event, the `retry:` hint, and the
  `Last-Event-ID` reconnect automatically. The assertion that `"after-close"`
  arrived is the proof.

## Caveats

- `streamable_http_app(...)` is a hosting entry that reshapes in a later
  release; this story calls it directly because the event-store and
  retry-interval kwargs are the point.
- DNS-rebinding protection is disabled (`transport_security=NO_DNS_REBIND`)
  because the in-process httpx client sends no `Origin` header. Drop the kwarg
  for a real deployment.
- `event_store.py` here is example-grade only (sequential IDs, no eviction). A
  production server would back the `EventStore` interface with persistent
  storage.

## Spec

[Resumability and Redelivery](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports#resumability-and-redelivery)
· SEP-1699 (server-initiated SSE close)

## See also

`standalone_get/` (the standalone-stream sibling of `close_sse_stream()`),
`reconnect/` (the modern-era reconnection story — persisted `DiscoverResult`,
no event store), `streaming/` (in-flight progress + cancellation without the
disconnect).
