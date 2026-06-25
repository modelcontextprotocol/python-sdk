# oauth

The full OAuth 2.1 authorization-code flow against an in-process Authorization
Server, over Streamable HTTP. On the **server** side: one `MCPServer(auth=...,
auth_server_provider=...)` constructor call co-hosts the RFC 9728
protected-resource metadata route, the AS routes (`/register`, `/authorize`,
`/token`, `/.well-known/oauth-authorization-server`) and the bearer-gated
`/mcp` endpoint on a single Starlette app. On the **client** side:
`OAuthClientProvider` is an `httpx.Auth` that reacts to the first `401` by
walking PRM discovery → AS metadata → DCR → PKCE authorize → token exchange →
bearer retry — all inside the first awaited request, with no user-visible
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

The port must be **8000**: the demo AS metadata (`_shared/auth.py` `BASE_URL`)
is pinned to it on both the client and server side, so on any other port the
PRM/AS discovery chain points at the wrong origin.

`OAUTH_DEMO_AUTO_CONSENT=1` makes the demo AS skip the consent screen and 302
straight back with `?code=...`; without it the authorize step returns
`error=interaction_required` so you can see where a real browser would open.

`Client(url)` has no `auth=` passthrough, so a target built from a bare URL
can't carry the flow. Both runners close that gap the same way: `run_client`
(terminal 2) and the pytest harness build an authed `httpx.AsyncClient` from
this module's `build_auth` export and hand `main` targets that are already
routed through it.

## What to look at

- **`client.py` — `Client(targets(), mode=mode)`, twice.** The target `main`
  receives is already authed. The first construction is where the whole flow
  happens: the first request `401`s and `OAuthClientProvider` runs PRM
  discovery → AS metadata → DCR → PKCE authorize → token exchange → bearer
  retry before `whoami`'s result reaches the body.
- **`client.py` — the second `Client(targets(), mode=mode)`.** A `Client`
  cannot be re-entered after `__aexit__`; reconnecting means constructing a new
  one. The provider's `TokenStorage` persisted the tokens and the DCR
  registration, so this one sends `Authorization: Bearer ...` on its very first
  request — no second `/authorize`, no second `/register`. The demo AS mints a
  fresh `client_id` per DCR call, so `whoami` returning the *same* `client_id`
  is the reuse proof.
- **`client.py` — `build_auth()`.** `OAuthClientProvider` is an `httpx.Auth`.
  `Client(url, auth=...)` is the ergonomic the SDK is missing; until it lands
  the auth has to be threaded onto the underlying `httpx.AsyncClient` by hand.
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
multi-connection `targets()` consumer, no auth).
