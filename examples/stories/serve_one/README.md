# serve-one

The kernel layer beneath `MCPServer.run()` / `run_server_from_args`. Every
transport entry composes the same three pieces: a `lowlevel.Server` (the
handler registry), a `Connection` (per-peer state), and a driver — `serve_one`
for one request → result dict, or `serve_connection` for a dispatcher loop.
This is what you write to bring up MCP over a custom transport. Uniquely, the
server file here builds the stdio entry by hand instead of importing
`stories._hosting`.

## Run it

```bash
# stdio (default — the client spawns server.py as a subprocess; its __main__
# is the hand-built serve_connection loop)
uv run python -m stories.serve_one.client
```

## What to look at

- `server.py::handle_one` — `Connection.from_envelope(...)` + `serve_one(...)`
  returns the raw result dict for one request. No handshake, no streams; the
  entry owns wire encoding and exception→error mapping.
- `server.py::main` — `JSONRPCDispatcher` + `Connection.for_loop(...)` +
  `serve_connection(...)`: exactly what `Server.run()` does internally for
  stdio.
- `server.py::SingleExchangeContext` — the per-request `DispatchContext` a
  custom entry must supply. The SDK ships no public concrete class for this
  yet.
- `client.py` — drives `handle_one` directly and asserts the raw result-dict
  shape (`structuredContent` / `content`), then proves the loop-mode driver
  works over the wire.

## Caveats

- **Deep imports** — `serve_one`, `serve_connection`, and `Connection` are only
  reachable at `mcp.server.runner` / `mcp.server.connection` today; a shorter
  `mcp.server.*` re-export is tracked for beta.
- **Lowlevel-only.** The drivers take a `lowlevel.Server` and `MCPServer` has
  no public accessor for its underlying one (`_lowlevel_server` is private), so
  there is no `MCPServer`-tier variant of this story. Build the lowlevel
  `Server` directly until that accessor lands.
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
· [2026 versioning — discover](https://modelcontextprotocol.io/specification/draft/server/discover)

## See also

`legacy_routing/` (composing `serve_one` behind `classify_inbound_request`),
`dual_era/` (`Connection.protocol_version` in handlers).
