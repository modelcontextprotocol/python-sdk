# custom-methods

Register and call a vendor-prefixed JSON-RPC method that is not part of the
MCP spec. The server uses the low-level `Server.add_request_handler` (there is
no `MCPServer` surface for this, so `server.py` is lowlevel-native and there is
no `server_lowlevel.py` sibling); the client drops to `client.session` to send
it.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.custom_methods.client

# against a running HTTP server
uv run python -m stories.custom_methods.server --http --port 8000 &
uv run python -m stories.custom_methods.client --http http://127.0.0.1:8000/mcp
```

## What to look at

- `client.py` `main` — the body opens with `Client(target, mode=mode)`. The
  vendor request rides whichever protocol era `mode` selects; nothing else in
  the story changes between eras.
- `server.py` `SearchParams` — subclasses `types.RequestParams` so `_meta`
  (and on a 2026-07-28 connection, the reserved `io.modelcontextprotocol/*`
  envelope keys) parse uniformly without extra code.
- `server.py` `add_request_handler("acme/search", SearchParams, search)` — the
  method string is the wire `method`; use a vendor prefix so it can never
  collide with a future spec method.
- `client.py` `client.session.send_request(...)` — `Client` only exposes spec
  verbs, so vendor methods go through the underlying `ClientSession`. The
  `cast("types.ClientRequest", ...)` is needed because `send_request`'s
  `request` parameter is currently typed as the closed spec union; widening it
  (or adding `Client.send_request`) is tracked for beta.

## Caveats

- The TypeScript SDK's equivalent example also shows a custom server→client
  **notification** (`acme/searchProgress`). The Python client currently drops
  any notification whose method is not in the spec registry
  (`ClientSession._on_notify` → `KeyError` → silent drop), and there is no
  `set_notification_handler` analogue. That half is omitted here.

## Spec

[Requests — basic protocol](https://modelcontextprotocol.io/specification/2025-11-25/basic#requests)
(JSON-RPC request shape; vendor method names live outside the spec's reserved
set).

## See also

`serve_one/` (the per-exchange driver that runs registered handlers),
`middleware/` (wrapping every registered handler, including vendor methods).
