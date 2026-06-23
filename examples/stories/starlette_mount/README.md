# starlette-mount

Embed an MCP server inside an existing Starlette (or FastAPI) app at a
sub-path, next to your own routes. `mcp.streamable_http_app()` returns a
mountable ASGI app; the two things to get right are the **path** (the default
`streamable_http_path="/mcp"` stacks under your mount prefix) and the
**lifespan** (Starlette does not run a mounted sub-app's lifespan, so the
parent must enter `mcp.session_manager.run()`).

## Run it

```bash
uv run python -m stories.starlette_mount.server --port 8000 &
curl http://127.0.0.1:8000/health        # → {"status":"ok"}
uv run python -m stories.starlette_mount.client --http http://127.0.0.1:8000/api/
```

## What to look at

- `server.py` `streamable_http_path="/"` — without this the endpoint would be
  `/api/mcp`; with it, `Mount("/api", ...)` serves MCP at `/api/` (trailing
  slash required — Starlette's `Mount` forwards `/api` as an empty path that
  the inner `/` route won't match).
- `server.py` `lifespan` — `mcp.session_manager.run()` **must** be entered by
  the parent app. Forget it and every MCP request hangs (the sub-app's own
  lifespan never fires under `Mount`).
- `server.py` `Route("/health", ...)` — non-MCP routes live alongside the
  mount; FastAPI users do the same with `app.mount("/api", mcp_app)`.

## Caveats

- DNS-rebinding protection is on by default; the example passes
  `transport_security=NO_DNS_REBIND` because the in-process test client sends
  no `Origin` header. Remove it (or configure allowed hosts) for a real
  deployment.
- The parent-lifespan dance is a known SDK ergonomics gap (other SDKs mount
  with no extra ceremony); tracked for the beta reshape. The recipe shown here
  is what works today.

## Spec

[Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports#streamable-http)

## See also

`stateless_legacy/` (the one-liner `mcp.streamable_http_app()` without a parent
app), `json_response/`, `legacy_routing/`. TS-SDK equivalent: `examples/hono/`.
