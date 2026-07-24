# legacy-routing

The exported era classifier. `classify_inbound_request(body, headers=...)` from
`mcp.shared.inbound` is the body-primary test for "is this a 2026-era request?";
wrap it as `classify_era()` to route eras to different backends in your own
ASGI/ingress layer. Unlike most SDKs, the Python SDK's built-in
`streamable_http_app()` already serves **sessionful** 2025 alongside stateless
2026 on one `/mcp` route — so the predicate is for when you need *different*
arms (per-era auth, separate ports, an existing v1 deployment to keep), not to
make dual-era work at all.

Also shown: the CORS recipe (methods, request headers, and `expose_headers`)
browser-based MCP clients need.

## Run it

```bash
# HTTP only — the predicate is an HTTP-transport concern. The client
# self-hosts the app on a free port, runs, then tears it down.
uv run python -m stories.legacy_routing.client --http
# same, against the lowlevel-API server variant
uv run python -m stories.legacy_routing.client --http --server server_lowlevel

# against a server you run yourself (real uvicorn on :8000)
uv run python -m stories.legacy_routing.server --port 8000 &
SERVER_PID=$!
uv run python -m stories.legacy_routing.client --http http://127.0.0.1:8000/mcp
kill "$SERVER_PID"
```

## What to look at

- `client.py` — two visible connections to the SAME `/mcp` endpoint from one
  `targets()` factory: `Client(targets(), mode=mode)` (default `"auto"` →
  `server/discover` → the modern arm) and `Client(targets(), mode="legacy")`
  (the `initialize` handshake → the legacy arm). Each asserts `which_arm`
  reports the era the built-in router actually dispatched to. The era decision
  is one explicit `mode=` argument at construction.
- `client.py` — the predicate then shown directly against a modern body, a
  legacy body, and a malformed-modern body. The runnable `build_app()` uses the
  SDK's built-in router; the predicate itself is exercised as a pure
  function — see the user-land composition recipe below for wiring it into
  your own ingress.
- `server.py` `classify_era` — the tri-state wrapper. `InboundModernRoute` →
  `"modern"`; rung-1 `INVALID_PARAMS` (no envelope keys) → `"legacy"`; any
  other `InboundLadderRejection` is a malformed-modern request to **reject**,
  not route to legacy. When headers are supplied, both `Mcp-Protocol-Version`
  and `Mcp-Method` must mirror the body — a disagreement (or an unsupported
  version) is what produces that third arm; `client.py` shows both.
- `server.py` `build_app` — `streamable_http_app()` + `CORSMiddleware`. The
  `which_arm` tool reads `ctx.request_context.protocol_version` to prove which
  path the built-in router took.
- `server_lowlevel.py` — the CORS recipe re-used from `server.py` (the
  `MCP_*` header and method constants); `build_app` wires `lowlevel.Server`
  instead of `MCPServer` and reads `ctx.protocol_version` directly. The
  predicate is tier-agnostic, so `classify_era` lives only in `server.py`.

## User-land composition (when you need different backends)

There is no `legacy="reject"` flag yet. To route eras to different handlers,
buffer the body, classify, replay:

```python
async def mcp_endpoint(scope, receive, send):
    body, replay = await buffer_body(receive)          # your ASGI helper
    headers = {k.decode("ascii").lower(): v.decode("latin-1") for k, v in scope["headers"]}
    match classify_era(json.loads(body or b"{}"), headers):
        case "legacy":
            await my_existing_v1_manager.handle_request(scope, replay, send)
        case "modern":
            await modern_manager.asgi_app(scope, replay, send)
        case rejection:
            await send_jsonrpc_error(send, rejection)  # map via ERROR_CODE_HTTP_STATUS
```

Non-POST verbs (`GET` standalone-SSE, `DELETE` session termination) are
sessionful-2025-only — route them straight to the legacy arm.

## Two ports instead of one

Run two `uvicorn` processes from the same `build_app()` on different ports and
put `classify_era()` (or a header check) in your ingress. Useful when the two
eras need different auth, rate limits, or scaling.

## Caveats

- The SDK's **built-in** routing is currently header-only — a 2026 client that
  omits `MCP-Protocol-Version` is mis-routed to legacy.
  `classify_inbound_request()` is body-primary and is what the built-in moves
  to in a later release; user-land routing with the predicate is already
  correct today.
- `ctx.request_context.protocol_version` is the interim 2-hop reach; a later
  release will shorten it.
- DNS-rebinding protection is on by default; the harness disables it
  (`NO_DNS_REBIND`) because the in-process httpx2 client sends no `Origin`.
  Drop the kwarg for a real deployment.
- `mcp.shared.inbound` is a deep import path — a shorter re-export is planned
  before beta.

## Spec

- [Versioning — backward compatibility](https://modelcontextprotocol.io/specification/draft/basic/versioning)
- [Transports — protocol version header](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)

## See also

`dual_era/` (the simple case: one factory, built-in routing, no predicate),
`stateless_legacy/` (`stateless_http=True`), `starlette_mount/` (mount inside
FastAPI).
