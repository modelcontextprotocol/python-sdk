# bearer-auth

Resource-server-only bearer auth. Pass a `TokenVerifier` + `AuthSettings`
(issuer, resource URL, required scopes) when building the streamable-HTTP app
and the SDK wires three things automatically: a bearer gate that answers 401 +
`WWW-Authenticate: Bearer ... resource_metadata=...` (or 403 `insufficient_scope`),
the RFC 9728 protected-resource-metadata document at
`/.well-known/oauth-protected-resource/mcp`, and the verified `AccessToken`
inside tool handlers via `get_access_token()`. The verifier here accepts one
static token — replace it with JWT verification or RFC 7662 introspection. No
authorization server; see `../oauth/` for the full grant flow.

## Run it

```bash
# start the bearer-gated server (real uvicorn on :8000)
uv run python -m stories.bearer_auth.server --port 8000 &

# connect with the demo bearer token
uv run python -m stories.bearer_auth.client --http http://127.0.0.1:8000/mcp

# lowlevel-API variant of the same app
uv run python -m stories.bearer_auth.server_lowlevel --port 8001 &
uv run python -m stories.bearer_auth.client --http http://127.0.0.1:8001/mcp
```

## Try it without the SDK client

```bash
# no token → 401 + WWW-Authenticate pointing at the PRM document
curl -i -X POST http://127.0.0.1:8000/mcp \
  -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'

# the RFC 9728 protected-resource-metadata document
curl -s http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp | jq
```

## What to look at

- `server.py` — `MCPServer(token_verifier=..., auth=AuthSettings(...))` is the
  whole recipe; `streamable_http_app()` reads those constructor kwargs and
  mounts the bearer gate + PRM route.
- `server_lowlevel.py` — same gate, but `lowlevel.Server` takes
  `auth=` / `token_verifier=` at **`streamable_http_app(...)` time**, not in the
  constructor. `mcp.server.auth.*` imports are allowed in lowlevel files
  (helper-tier).
- `whoami()` — `get_access_token()` returns the per-HTTP-request `AccessToken`.
  It is **not** on `Context` (unlike other SDKs' `ctx.authInfo`); a later
  release will namespace it as `ctx.transport.auth`.
- `client.py` — `http_client_kw` carries the `Authorization` header at the
  `httpx.AsyncClient` layer because `Client(url)` has no `auth=` passthrough
  yet. The `__main__` block shows the hand-built
  `httpx.AsyncClient → streamable_http_client → Client` chain a real caller
  would write today.

## Caveats

- `transport_security=NO_DNS_REBIND` — DNS-rebinding protection is on by default
  for localhost binds; the harness disables it because the in-process httpx
  client sends no `Origin` header. Drop the kwarg for a real deployment.
- `RESOURCE_URL` is hard-coded to port 8000 (the harness's in-process origin).
  If you change `--port`, edit `RESOURCE_URL` to match or the PRM document's
  `resource` field will be wrong.
- Auth is HTTP-only; over stdio or the in-memory transport `get_access_token()`
  returns `None` and there is no gate.
- The 401/403 status codes and `WWW-Authenticate` header are HTTP-level and
  `Client` cannot observe them; they are pinned by
  `tests/interaction/auth/test_bearer.py` and shown via `curl` above.

## Spec

[Authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
· RFC 9728 (Protected Resource Metadata) · RFC 6750 (`WWW-Authenticate: Bearer`)

## See also

`oauth/` (full authorization-code grant with an in-process AS) ·
`oauth_client_credentials/` (M2M `client_credentials` grant) ·
`stateless_legacy/` (the un-gated hosting baseline).
