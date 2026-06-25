# stateless-legacy

The one-liner HTTP deploy. `MCPServer.streamable_http_app(stateless_http=True)`
returns a complete ASGI app that serves **both** protocol eras on `/mcp`: 2025
clients get the `initialize` handshake answered statelessly (no `Mcp-Session-Id`,
fresh transport per request, horizontally scalable), 2026 clients get the
per-request envelope path. Hand it straight to uvicorn — no session-manager
wiring, no era flag. The client connects once per era and asserts the same
`greet` tool answers identically either way.

## Run it

```bash
# start the server (real uvicorn on :8000)
uv run python -m stories.stateless_legacy.server --port 8000 &

# connect once as a modern client and once as a legacy client
uv run python -m stories.stateless_legacy.client --http http://127.0.0.1:8000/mcp

# lowlevel-API variant of the same app
uv run python -m stories.stateless_legacy.server_lowlevel --port 8001 &
uv run python -m stories.stateless_legacy.client --http http://127.0.0.1:8001/mcp
```

## What to look at

- `client.py` — two visible `Client(targets(), mode=...)` constructions against
  the same URL. The first connects at the caller's `mode` (the real-user
  `"auto"` default routes to the 2026 envelope path); the second pins
  `mode="legacy"` and runs the `initialize` handshake. `client.protocol_version`
  is the era-neutral accessor: two negotiated versions, identical tool result.
- `server.py` — `stateless_http=True` is the only knob; era routing is automatic
  inside `StreamableHTTPSessionManager.handle_request`. The returned `Starlette`
  already wires `lifespan=session_manager.run()`, so `uvicorn.run(app, ...)`
  works with no parent-lifespan ceremony.
- `server_lowlevel.py` — `lowlevel.Server.streamable_http_app()` is the same
  call; `MCPServer` delegates to it.

## Caveats

- `transport_security=NO_DNS_REBIND` — DNS-rebinding protection is on by default
  for localhost binds; the harness disables it because the in-process httpx
  client sends no `Origin` header. Drop the kwarg for a real deployment.
- `streamable_http_app()` reshapes in a later release; the call is isolated in
  `build_app()` so the change touches one line per server file.

## Spec

[Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports#streamable-http)
· [Versioning — backward compatibility](https://modelcontextprotocol.io/specification/draft/basic/versioning)

## See also

`dual_era/` (era branching inside a tool handler) · `legacy_routing/`
(`is_legacy_request()` for sessionful-2025 + modern on one mount) ·
`starlette_mount/` (mounting under FastAPI/Starlette with parent lifespan) ·
`json_response/` (`json_response=True` and what it drops).
