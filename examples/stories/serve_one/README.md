# serve-one

The kernel layer beneath `MCPServer.run()` / `run_server_from_args`. Every
transport entry composes the same three pieces: a `lowlevel.Server` (the
handler registry), a `Connection` (per-peer state), and a driver — `serve_one`
for one request → result dict, or `serve_connection` for a dispatcher loop.
This is what you write to bring up MCP over a custom transport. Uniquely, the
server files here build the stdio entry by hand instead of importing
`stories._hosting`.

## Run it

```bash
# stdio (default — the client spawns server.py as a subprocess; its __main__
# is the hand-built serve_loop recipe)
uv run python -m stories.serve_one.client

# drive the lowlevel hand-built loop instead
uv run python -m stories.serve_one.client --server server_lowlevel
```

## What to look at

- `server_lowlevel.py::handle_one` — `Connection.from_envelope(...)` +
  `serve_one(...)` returns the raw result dict for one request. No handshake,
  no streams; the entry owns wire encoding and exception→error mapping.
- `server_lowlevel.py::main` — `JSONRPCDispatcher` + `Connection.for_loop(...)`
  + `serve_connection(...)`: exactly what `Server.run()` does internally for
  stdio.
- `server_lowlevel.py::SingleExchangeContext` — the per-request
  `DispatchContext` a custom entry must supply. The SDK ships no public
  concrete class for this yet.
- `server.py::main` — `serve_loop(...)` over an `MCPServer`'s underlying
  `lowlevel.Server`; surfaces the missing public accessor.
- `client.py` — drives `handle_one` directly and asserts the raw result-dict
  shape (`structuredContent` / `content`), then proves the loop-mode driver
  works over the wire.

## Caveats

- **Deep imports** — `serve_one`, `serve_connection`, `serve_loop`,
  `Connection` are only reachable at `mcp.server.runner` /
  `mcp.server.connection` today; a shorter `mcp.server.*` re-export is tracked
  for beta.
- **`MCPServer` accessor** — `server.py` reaches `mcp._lowlevel_server` because
  there's no public way to hand an `MCPServer` to the drivers. Prefer the
  lowlevel variant until that lands.
- **No public `DispatchContext`** — `SingleExchangeContext` is hand-rolled
  boilerplate; a public helper (or a `serve_one` overload that builds one) is
  tracked for beta.
- **Lifespan** — the transport entry enters `server.lifespan(server)` **once**
  and threads `lifespan_state` to every `handle_one()` call; never enter it
  per-request.
- `ServerRunner` is kernel-internal; never construct it directly. The
  free-function drivers are the supported surface.

## Spec

[Architecture — lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
· [2026 versioning — discover](https://modelcontextprotocol.io/specification/2026-07-28/server/discover)

## See also

`client_session/` (the client-side mechanics counterpart), `legacy_routing/`
(composing `serve_one` behind `classify_inbound_request`), `dual_era/`
(`Connection.protocol_version` in handlers).
