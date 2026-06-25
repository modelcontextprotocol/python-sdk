# middleware

Register a single `async (ctx, call_next) -> result` function on
`Server.middleware` to observe or alter every request and notification the
server receives, across both protocol eras and any transport. Middleware sits
*outside* method lookup and params validation, so it sees `initialize`,
`server/discover`, `notifications/*`, and unknown methods too. The chain runs
outermost-first.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.middleware.client

# against a running HTTP server
uv run python -m stories.middleware.server --http --port 8000 &
uv run python -m stories.middleware.client --http http://127.0.0.1:8000/mcp
```

## What to look at

- `client.py` `main` — opens with `async with Client(target, mode=mode)`. The
  story owns that construction; the harness only picks the target and era.
  Middleware is invisible from this side — only the `audit_log` result proves
  the wrap happened.
- `server.py` — `server.middleware.append(record_calls)` is the public
  registration point on `mcp.server.lowlevel.Server`.
- `client.py` — the asserted log ends at `"tools/call"` without a `:done`
  suffix: `audit_log` runs *inside* `call_next(ctx)`, so the `finally` hasn't
  fired yet. That's the wrap.

## Caveats

- **Lowlevel-only.** `Server.middleware` on `mcp.server.lowlevel.Server` is the
  one public hook; `MCPServer` has no public accessor for it yet (a
  `MCPServer.middleware` accessor is planned before beta).
- The middleware signature is **provisional** (see the TODO in
  `src/mcp/server/lowlevel/server.py`): it tightens to a covariant `Context[L]`
  and gains an outbound seam before v2 final.
- `ServerMiddleware` / `CallNext` / `HandlerResult` are imported from
  `mcp.server.context` (helper tier); not re-exported at `mcp.server.lowlevel`.
- Do **not** `await ctx.session.send_request(...)` while wrapping `initialize`
  — `initialize` is dispatched inline and the outbound channel isn't open yet.
- To rewrite `ctx.method` / `ctx.params` before the handler runs, pass an
  adjusted context through: `await call_next(dataclasses.replace(ctx, ...))`.
  `docs/migration.md` shows the full recipe.

## Spec

Middleware is SDK architecture, not an MCP spec feature.

## See also

`custom_methods/` (a vendor `acme/search` handler registered with
`add_request_handler` — middleware wraps it like any spec method),
`src/mcp/server/_otel.py` (`OpenTelemetryMiddleware`, the SDK's own consumer).
