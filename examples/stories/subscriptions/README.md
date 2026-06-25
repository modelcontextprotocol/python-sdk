# subscriptions

The 2026-era `subscriptions/listen` channel: the server publishes change events
through a `ServerEventBus`, and `Client.listen()` opens an async iterator over
them. Replaces the handshake-era `resources/subscribe` + standalone-GET
notification path.

**Status: not yet implemented** ([#2901](https://github.com/modelcontextprotocol/python-sdk/issues/2901)).
The lowlevel registration surface exists on `main` as of
[#2967](https://github.com/modelcontextprotocol/python-sdk/pull/2967)
(`ae13ede`), which added the lowlevel `on_subscriptions_listen` handler slot.
There is no `Client.listen()` or `ServerEventBus` yet; this story graduates
from a README stub to a runnable example once this branch's base includes that
commit.

## Spec

[Subscriptions — basic utilities](https://modelcontextprotocol.io/specification/draft/basic/utilities/subscriptions)

## Working example elsewhere

The TypeScript SDK ships a runnable `subscriptions` story:
[typescript-sdk/examples/subscriptions](https://github.com/modelcontextprotocol/typescript-sdk/tree/main/examples/subscriptions).

## See also

`standalone_get/` (handshake-era server-initiated notifications), `resources/`
(legacy `subscribe` deliberately omitted).
