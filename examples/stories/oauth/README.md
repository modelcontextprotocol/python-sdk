# oauth

The full OAuth 2.1 authorization-code flow against an in-process Authorization
Server, over Streamable HTTP. On the **server** side: one `MCPServer(auth=...,
auth_server_provider=...)` constructor call co-hosts the RFC 9728
protected-resource metadata route, the AS routes (`/register`, `/authorize`,
`/token`, `/.well-known/oauth-authorization-server`) and the bearer-gated
`/mcp` endpoint on a single Starlette app. On the **client** side:
`OAuthClientProvider` is an `httpx.Auth` that reacts to the first `401` by
walking PRM discovery → AS metadata → DCR → PKCE authorize → token exchange →
bearer retry — all inside `Client.__aenter__`, with no user-visible
`UnauthorizedError`.

## Run it

```bash
# terminal 1 — co-hosted AS + bearer-gated /mcp on :8000
OAUTH_DEMO_AUTO_CONSENT=1 uv run python -m stories.oauth.server --port 8000

# terminal 2 — authorization-code flow (headless: redirect followed in-process)
uv run python -m stories.oauth.client --http http://127.0.0.1:8000/mcp

# lowlevel-API variant of the same app
OAUTH_DEMO_AUTO_CONSENT=1 uv run python -m stories.oauth.server_lowlevel --port 8000
```

`OAUTH_DEMO_AUTO_CONSENT=1` makes the demo AS skip the consent screen and 302
straight back with `?code=...`; without it the authorize step returns
`error=interaction_required` so you can see where a real browser would open.

## What to look at

- **`server.py` — `MCPServer(auth=..., auth_server_provider=...)`.** The
  constructor wires everything; `streamable_http_app()` reads it back. (Don't
  also pass `token_verifier=` — `auth_server_provider` and `token_verifier` are
  mutually exclusive.) The `whoami` tool reads the validated principal via
  `get_access_token()` — a per-HTTP-request contextvar set by
  `AuthContextMiddleware`, not per-session.
- **`server_lowlevel.py`** — same wire shape, but `lowlevel.Server` takes
  `auth=`/`token_verifier=`/`auth_server_provider=` on `streamable_http_app()`
  rather than the constructor. `mcp.server.auth.*` is a helper tier the lowlevel
  API may import directly.
- **`client.py` — `_auth_with()` / `build_auth()`.** `OAuthClientProvider` is
  threaded onto `httpx.AsyncClient.auth`; `Client(url)` has no `auth=` kwarg
  yet, so the transport is built by hand:
  `Client(streamable_http_client(url, http_client=http))`.
- **`client.py` — token reuse.** A `Client` cannot be re-entered after
  `__aexit__`. The third connection reuses the same `TokenStorage`, so it sends
  `Authorization: Bearer ...` on the very first request — no `/authorize`, no
  `/register` — and `whoami` returns the DCR-persisted `client_id`.

## Caveats

- `transport_security=NO_DNS_REBIND` — DNS-rebinding protection is on by default
  and the in-process httpx bridge sends no `Origin` header. Drop the kwarg for a
  real deployment.
- `HeadlessOAuth` only works because the demo AS auto-consents; a real
  `redirect_handler` would open a browser and a real `callback_handler` would
  run a loopback HTTP listener for the redirect.
- The `mcp.server.auth.*` import paths are deep (no `mcp.server` re-export yet).

## Spec

[Authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)

## See also

`bearer_auth/` (RS-only, static token, no AS) · `oauth_client_credentials/`
(M2M `client_credentials` grant — no browser, no DCR) · `reconnect/` (the other
`connect: Connect` consumer).
