# lifespan

Process-scoped dependency injection. Pass an `@asynccontextmanager` as
`lifespan=` to acquire resources (a database pool, an HTTP client) once at
startup and release them at shutdown; tool bodies read the yielded state via
the injected `Context` — no module-level globals.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.lifespan.client

# HTTP — the client self-hosts the server on a free port, runs, then tears it down
uv run python -m stories.lifespan.client --http
# same, against the lowlevel-API server variant
uv run python -m stories.lifespan.client --http --server server_lowlevel
```

## What to look at

- `client.py` `main` — opens with `Client(target, mode=mode)`; the story owns
  the construction, the harness only chooses the target and era. Lifespan is
  invisible from here: the client speaks plain MCP, and the `lookup` results
  are the only proof the yielded state was wired through.
- `app_lifespan` in `server.py` — the `try / yield / finally` shape is the
  startup/shutdown contract; the `finally` block runs once on process exit, not
  per request.
- `ctx.request_context.lifespan_context.db` in the `lookup` tool — the interim
  3-hop access path on `MCPServer`'s `Context`.
- `server_lowlevel.py` reaches the same state via `ctx.lifespan_context.db` —
  one hop, because lowlevel handlers receive `ServerRequestContext` directly.

## Caveats

- `ctx.request_context.lifespan_context` is the interim path; a later release
  will shorten this to `ctx.state.*`. The lowlevel `ctx.lifespan_context` path
  is unaffected.
- **v1 → v2 scope change** — in v1.x, `lifespan` was entered once per
  `Server.run()` call: once per *session* for stateful streamable HTTP and once
  per *request* under `stateless_http=True` (stdio was already per-process). In
  v2 it is entered once per process regardless of transport. See
  `docs/migration.md` ("Streamable HTTP: lifespan now entered once at manager
  startup").

## Spec

[Lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)

## See also

`stickynotes/` (lifespan-held mutable state with change notifications),
`serve_one/` (threading `lifespan_state` into the kernel by hand).
