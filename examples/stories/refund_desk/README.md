# refund-desk

Resolver dependency injection: a tool parameter annotated `Annotated[T,
Resolve(fn)]` is filled by running the resolver `fn` before the tool body,
instead of from the LLM-supplied arguments. Here `refund_order(order_id,
reason)` refunds what the order record says — `cents` is resolver-computed and
does not appear in the input schema at all, so the model cannot supply or
inflate the amount. Resolvers form a DAG (`load_order` → `refund_scope` →
`refund_amount` / `ask_restock`), may return `Elicit[...]` to ask the human,
and run at most once per call. A resolver's own plain parameters are filled
from the tool's arguments by name — `load_order(order_id)` receives the
`order_id` the model passed to `refund_order`.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.refund_desk.client

# HTTP — the client self-hosts the server on a free port, runs, then tears it
# down (--legacy: resolver elicitation rides the push request today; the
# manifest pins this era, so bare --http runs the same leg)
uv run python -m stories.refund_desk.client --http --legacy
```

## What to look at

- `server.py` `refund_order` — the signature is the whole story: `order_id` and
  `reason` are model-facing; `cents` and `restock` carry `Resolve(...)` markers
  and never reach the input schema. `client.py` asserts `properties` and
  `required` are exactly `{order_id, reason}`.
- `server.py` `refund_scope` — the no-round-trip fast path: a one-line order
  returns `Scope(full=True)` directly; only a multi-line order returns
  `Elicit(...)`. The ORD-7001 call completes with zero elicitations.
- `server.py` `_scoped` — the elicited SKU is human-typed free text; it is
  validated against the order (`ToolError` on a miss) before any amount is
  computed.
- The decline contrast: `refund_amount` takes `scope` **unwrapped**, so
  declining the scope question aborts the whole `cents` chain with an error
  containing the framework's
  `Resolver for parameter 'scope' could not resolve: elicitation was decline`
  (the client sees it behind the usual `Error executing tool refund_order:`
  prefix); `restock` keeps the `ElicitationResult` union, so declining restock
  still refunds — just with `restocked: false`.
- `client.py` — the scope counter proves memoization from outside: one call
  consumes `refund_scope` from two resolvers but the question fires once.

## Caveats

- **Decline order.** A declined unwrapped dependency aborts resolution in
  tool-signature order — `cents` resolves before `restock`, so `ask_restock`
  never runs. Don't rely on a later resolver's side effects after an earlier
  consumer can abort.
- **Memoization scope.** Each resolver runs at most once per `tools/call`,
  keyed by function identity; nothing is cached across calls or connections.
- **Validate elicited values.** Elicited answers are human-typed; check them
  against your records (as `_scoped` does) before acting on them.

## Spec

[Elicitation — client features](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation)

## See also

`legacy_elicitation/` (the push mechanism resolver elicitation rides on today),
`mrtr/` (the 2026 `input_required` carrier; resolver DI will ride it once the
SDK wires them together).
