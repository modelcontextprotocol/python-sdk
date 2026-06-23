# oauth-client-credentials

OAuth 2.0 **`client_credentials`** grant — machine-to-machine MCP auth, no
browser. A backend service authenticates *as itself* by presenting a
pre-registered `client_id`/`client_secret` directly to the AS token endpoint;
the SDK's `ClientCredentialsOAuthProvider` handles 401-challenge → PRM/AS
discovery → token POST → Bearer attachment automatically.

## Run it

```bash
# start the server (real uvicorn on :8000 — auth is HTTP-only)
uv run python -m stories.oauth_client_credentials.server --port 8000 &
uv run python -m stories.oauth_client_credentials.client --http http://127.0.0.1:8000/mcp

# lowlevel-API variant of the same app
uv run python -m stories.oauth_client_credentials.server_lowlevel --port 8000 &
uv run python -m stories.oauth_client_credentials.client --http http://127.0.0.1:8000/mcp
```

OAuth is an HTTP-layer concern; stdio servers receive credentials via the
environment per the spec, so there is no stdio leg.

## What to look at

- `client.py` `build_auth` — five lines of `ClientCredentialsOAuthProvider`
  config is all the caller writes; the SDK does RFC 9728 PRM →
  RFC 8414 AS-metadata discovery and token exchange on the first 401.
- `server.py` `token_endpoint` — the *entire* AS for this grant: validate
  HTTP-Basic `client_id:client_secret`, mint a token, return RFC 6749 JSON.
  The SDK's built-in `auth_server_provider=` only routes
  `authorization_code`/`refresh_token`, so M2M servers mount their own `/token`.
- `server.py` `whoami` — `get_access_token()` is how a tool reads the
  authenticated principal (`client_id`, `scopes`) from the request context.
- `server_lowlevel.py` — identical auth wiring via
  `Server.streamable_http_app(auth=..., token_verifier=...,
  custom_starlette_routes=[...])`; only the tool registration differs.

## Caveats

- `Client(url)` has no `auth=` passthrough — you build `httpx.AsyncClient` →
  `streamable_http_client(url, http_client=hc)` → `Client(transport)` yourself.
  The `__main__` block shows the chain.
- `transport_security=NO_DNS_REBIND` — DNS-rebinding protection is on by
  default for localhost binds; the harness disables it because the in-process
  httpx client sends no `Origin` header. Drop the kwarg for a real deployment.
- `OAuthMetadata.authorization_endpoint` is a required field even though a
  `client_credentials`-only AS has no authorize endpoint; the server sets a
  dummy URL.

## `private_key_jwt`

Swap `ClientCredentialsOAuthProvider` for `PrivateKeyJWTOAuthProvider` to
authenticate the token request with a signed assertion (RFC 7523 §2.2) instead
of a shared secret. Not exercised here because the demo AS only validates
`client_secret_basic`.

## Spec

[Authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)

## See also

`oauth/` (interactive `authorization_code` + PKCE — user-facing flow) ·
`bearer_auth/` (static token, no AS — simplest gating).
