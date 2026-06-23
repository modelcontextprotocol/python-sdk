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

- `server_lowlevel.py` — `server.middleware.append(record_calls)` is the public
  registration point on `mcp.server.lowlevel.Server`.
- `server.py` — `MCPServer` has no public hook yet, so the example reaches
  `mcp._lowlevel_server.middleware` (a public `MCPServer.middleware` accessor
  is planned before beta — prefer the lowlevel variant until then).
- `client.py` — the asserted log ends at `"tools/call"` without a `:done`
  suffix: `audit_log` runs *inside* `call_next(ctx)`, so the `finally` hasn't
  fired yet. That's the wrap.

## Caveats

- The middleware signature is **provisional** (see the TODO in
  `src/mcp/server/lowlevel/server.py`): it tightens to a covariant `Context[L]`
  and gains an outbound seam before v2 final.
- `ServerMiddleware` / `CallNext` / `HandlerResult` are imported from
  `mcp.server.context` (helper tier); not re-exported at `mcp.server.lowlevel`.
- Do **not** `await ctx.session.send_request(...)` while wrapping `initialize`
  — `initialize` is dispatched inline and the outbound channel isn't open yet.

## Spec

Middleware is SDK architecture, not an MCP spec feature.

## See also

`custom_methods/` (rewrite `ctx.method` / `ctx.params` via
`dataclasses.replace(ctx, ...)` before `call_next`),
`src/mcp/server/_otel.py` (`OpenTelemetryMiddleware`, the SDK's own consumer).
