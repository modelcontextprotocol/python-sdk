# subscriptions

Server-originated change notifications on the 2026-07-28 protocol. A client
opens one `subscriptions/listen` request whose response **is** the stream; the
server publishes with `ctx.notify_resource_updated(uri)` /
`ctx.notify_tools_changed()` and the SDK does the wire work (ack-first,
per-stream filtering, subscription-id tagging). Replaces the handshake-era
`resources/subscribe` + standalone-GET notification path.

The client edits a note it did not subscribe to (silence), edits the one it
did (a tagged `notifications/resources/updated`), registers a tool at runtime
(`notifications/tools/list_changed`, then re-lists and calls it), and finally
closes the stream by cancelling the parked request.

## Run it

```bash
# HTTP — the client self-hosts the server on a free port, runs, then tears it
# down (subscriptions/listen is 2026-era only)
uv run python -m stories.subscriptions.client --http
# same, against the lowlevel-API server variant
uv run python -m stories.subscriptions.client --http --server server_lowlevel
```

## What to look at

- `client.py` — stream frames arrive as ordinary server notifications via the
  constructor-only `message_handler=`. There is no client-side listen API yet,
  so opening the stream drops to the `client.session` escape hatch; the request
  parks for the stream's lifetime and the client closes the stream by
  cancelling it. Every frame's `_meta["io.modelcontextprotocol/subscriptionId"]`
  is the listen request's JSON-RPC id.
- `server.py` — publishing is one `await ctx.notify_*()` line per change; the
  filter, the tagging, and the ack ordering are the SDK's job. Publishing with
  no subscribers is a no-op.
- `server_lowlevel.py` — the same machinery held by hand: an
  `InMemorySubscriptionBus`, handlers that `await bus.publish(...)`, and
  `ListenHandler(bus)` passed as `on_subscriptions_listen=`. A multi-replica
  deployment swaps the bus for one backed by its own pub/sub
  (`MCPServer(subscriptions=...)` on the high-level server).

## Caveats

- 2026-era only: on a 2025 connection the method does not exist (clients there
  use `resources/subscribe` and unsolicited notifications instead), so the
  story pins the modern era and has no legacy leg.
- No replay: events published while no stream is open are not queued. The
  contract after a dropped stream is re-listen and re-fetch.

## Spec

[Subscriptions — basic utilities](https://modelcontextprotocol.io/specification/draft/basic/utilities/subscriptions)

## See also

`streaming/` (request-scoped notifications), `events/` (the events extension
on top of this channel, deferred), and `docs/advanced/subscriptions.md` (the
narrative version).
