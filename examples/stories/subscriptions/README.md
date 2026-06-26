# subscriptions

The 2026-era `subscriptions/listen` channel: the server publishes change events
through a `ServerEventBus`, and `Client.listen()` opens an async iterator over
them. Replaces the handshake-era `resources/subscribe` + standalone-GET
notification path.

**Status: not yet implemented** ([#2901](https://github.com/modelcontextprotocol/python-sdk/issues/2901)).
The lowlevel registration surface is in this base —
[#2967](https://github.com/modelcontextprotocol/python-sdk/pull/2967)
(`ae13ede`) added the lowlevel `on_subscriptions_listen` handler slot — but
there is no `Client.listen()` or `ServerEventBus` yet. The runnable story is
deliberately a follow-up PR to keep this one reviewable.

## Spec

[Subscriptions — basic utilities](https://modelcontextprotocol.io/specification/draft/basic/utilities/subscriptions)

## Working example elsewhere

The TypeScript SDK ships a runnable `subscriptions` story:
[typescript-sdk/examples/subscriptions](https://github.com/modelcontextprotocol/typescript-sdk/tree/main/examples/subscriptions).

## See also

`standalone_get/` (handshake-era server-initiated notifications), `resources/`
(legacy `subscribe` deliberately omitted).
