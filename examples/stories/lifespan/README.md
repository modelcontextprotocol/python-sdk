# lifespan

Process-scoped dependency injection. Pass an `@asynccontextmanager` as
`lifespan=` to acquire resources (a database pool, an HTTP client) once at
startup and release them at shutdown; tool bodies read the yielded state via
the injected `Context` — no module-level globals.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.lifespan.client

# against a running HTTP server
uv run python -m stories.lifespan.server --http --port 8000 &
uv run python -m stories.lifespan.client --http http://127.0.0.1:8000/mcp
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
- **v1 → v2 scope change** — in v1.x, `lifespan` was entered once *per
  connection*; in v2 it is entered once *per process*. See `docs/migration.md`
  ("lifespan now per-process").

## Spec

[Lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)

## See also

`stickynotes/` (lifespan-held mutable state with change notifications),
`serve_one/` (threading `lifespan_state` into the kernel by hand).
