# json-response

`streamable_http_app(json_response=True)` — one `application/json` body per
request instead of an SSE stream. Useful for serverless / edge runtimes that
can't hold a stream open. The 2026-07-28 path is stateless and JSON-only today
regardless of the flag; setting it makes the legacy (2025-era) branch on the
same endpoint behave the same way.

## Run it

```bash
# HTTP — the client self-hosts the app on a free port, runs the high-level
# Client + raw-envelope probe, then tears it down
uv run python -m stories.json_response.client --http
# same, against the lowlevel-API server variant
uv run python -m stories.json_response.client --http --server server_lowlevel

# against a server you run yourself (real uvicorn on :8000)
uv run python -m stories.json_response.server --port 8000 &
SERVER_PID=$!
uv run python -m stories.json_response.client --http http://127.0.0.1:8000/mcp

# or POST the raw envelope yourself
curl -s http://127.0.0.1:8000/mcp \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -H 'mcp-protocol-version: 2026-07-28' \
  -H 'mcp-method: tools/list' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientInfo":{"name":"curl","version":"0"},"io.modelcontextprotocol/clientCapabilities":{}}}}'
kill "$SERVER_PID"
```

## What to look at

- `client.py` `main` — `async with Client(target, mode=mode) as client:` is an
  ordinary high-level client; nothing about JSON mode is visible from this side.
  The same `main` also takes the raw `httpx2.AsyncClient` so it can prove what
  the wire looks like underneath.
- `client.py` `RAW_ENVELOPE_BODY` / `MODERN_HEADERS` — the exact 2026 wire
  shape: three `io.modelcontextprotocol/*` `_meta` keys replace the initialize
  handshake; `MCP-Protocol-Version` + `Mcp-Method` headers mirror the body so
  gateways can route without parsing JSON. `main` posts it by hand and asserts
  a single `application/json` response with no `Mcp-Session-Id`.
- `server.py` `greet` calls `ctx.report_progress(0.5)` — and `main` proves the
  client's `progress_callback` is **never invoked**: JSON mode has no
  back-channel for mid-call notifications (the `progress_seen == []` assertion
  flips to `== [0.5]` once SSE buffering lands for the modern path).
- `server_lowlevel.py` — same ASGI app built from `lowlevel.Server`; the
  `json_response=` / `transport_security=` knobs live on `streamable_http_app`,
  not the server class.

## Caveats

- DNS-rebinding protection is on by default; the harness disables it via
  `NO_DNS_REBIND` because the in-process httpx2 client sends no `Origin` header.
- The `streamable_http_app()` call shape here will move when the free-function
  entry lands (see `_hosting.py`).
- `Mcp-Name` is omitted for `tools/list` because the SDK only emits it on
  `tools/call` today.

## Spec

[Streamable HTTP — 2026-07-28](https://modelcontextprotocol.io/specification/draft/basic/transports/streamable-http)
· [SEP-2243 standard headers](https://modelcontextprotocol.io/specification/draft/basic/transports/streamable-http#standard-request-headers)

## See also

`stateless_legacy/` (the one-liner `stateless_http=True` deploy),
`legacy_routing/` (route by era at the entry), `streaming/` (progress that *is*
delivered — over stdio/SSE).
