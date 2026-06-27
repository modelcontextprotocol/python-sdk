# identity-assertion

SEP-990 (Enterprise-Managed Authorization): the enterprise identity provider,
not the end user, decides which MCP servers a client may reach. The IdP signs
that decision into an Identity Assertion JWT Authorization Grant (an ID-JAG);
the client presents it to the MCP authorization server under the RFC 7523
`jwt-bearer` grant and gets an ordinary, audience-restricted access token back.
No browser, no consent screen, no dynamic client registration, no refresh
token. This story co-hosts the authorization server and the bearer-gated MCP
server on one app, stands in for the IdP with an in-process signer, and proves
the user the IdP named is the user the tool sees.

## Run it

```bash
# HTTP, self-hosted: the client spawns the co-hosted AS + MCP app, presents an
# ID-JAG, and asserts `whoami` reports the IdP's subject. Self-hosting uses
# this story's fixed :8000 (the issuer/PRM metadata bake it in), so :8000 must
# be free.
uv run python -m stories.identity_assertion.client --http
# same, against the lowlevel-API server variant
uv run python -m stories.identity_assertion.client --http --server server_lowlevel

# against a server you run yourself (real uvicorn on :8000). The next section's
# curl probes use it too and `kill` it when done.
uv run python -m stories.identity_assertion.server --port 8000 &
SERVER_PID=$!
uv run python -m stories.identity_assertion.client --http http://127.0.0.1:8000/mcp
```

`Client(url)` has no `auth=` passthrough, so both runners thread the module's
`build_auth` export (an `IdentityAssertionOAuthProvider`) onto the
`httpx.AsyncClient` underneath the transport and hand `main` a target that is
already routed through it.

## Try it without the SDK client

```bash
# the AS metadata advertises the jwt-bearer grant AND the ID-JAG grant profile
curl -s http://127.0.0.1:8000/.well-known/oauth-authorization-server \
  | jq '{grant_types_supported, authorization_grant_profiles_supported}'

# dynamic client registration refuses the jwt-bearer grant: an ID-JAG client
# must be pre-registered out of band
curl -si http://127.0.0.1:8000/register -H 'content-type: application/json' \
  -d '{"redirect_uris":["http://localhost:3030/cb"],"grant_types":["authorization_code","urn:ietf:params:oauth:grant-type:jwt-bearer"]}' \
  | head -1

# done with the server you started in "Run it"
kill "$SERVER_PID"
```

## What to look at

- `client.py` `fetch_id_jag` — the one seam the SDK leaves you: given the
  authorization server's issuer and the MCP server's resource identifier,
  return a fresh ID-JAG. In production this is an RFC 8693 token exchange
  against your IdP; here it calls the stand-in signer in `idp.py`.
- `client.py` `build_auth` — `IdentityAssertionOAuthProvider` is the same
  `httpx.Auth` shape as every other provider. Note `issuer=ISSUER` with the
  trailing slash: the provider compares it to the metadata document's `issuer`
  by simple string comparison and refuses a mismatch before sending anything.
- `server.py` `exchange_identity_assertion` — the whole authorization-server
  hook. The SDK authenticates the client and gates the grant; the signature,
  `typ`, `aud`, `client_id`-match, `jti`-replay, and audience-restriction
  checks inside the hook are the implementation's job.
- `server.py` `build_app` — `auth_settings(identity_assertion_enabled=True)`
  is the one flag. Off (the default), `/token` answers the grant with
  `unsupported_grant_type` even when the hook is implemented.
- `idp.py` — the claims an ID-JAG carries (`iss`, `sub`, `aud`, `client_id`,
  `resource`, `scope`, `jti`, `iat`, `exp`) and its `typ: oauth-id-jag+jwt`
  header.

## Caveats

- The IdP here is a module, not a service, and it signs with a shared HMAC
  secret so the client process and a separately launched server process agree
  on it. A real IdP signs with its private key, the authorization server
  verifies against the IdP's published JWKS, and the client obtains the ID-JAG
  over the network with an RFC 8693 token exchange.
- Co-hosting the authorization server and the MCP server on one app
  (`auth_server_provider=`) is a demo convenience. SEP-990's model keeps them
  separate, and either way the client only ever learns about the authorization
  server from its own configuration, never from the MCP server.
- The provider's state is in-memory demo state: `seen_jtis` and the issued
  tokens only ever grow. A real server evicts a `jti` once the assertion's
  `exp` has passed and expires tokens out of its own store.
- `transport_security=NO_DNS_REBIND` is harness-only; drop it for a real
  deployment.
- Auth is HTTP-only; over stdio or the in-memory transport there is no gate.

## Spec

[Enterprise-Managed Authorization (SEP-990)](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization)
· RFC 7523 (JWT bearer grant: the leg the SDK implements)
· RFC 8693 (token exchange: the IdP leg the SDK leaves to you)
· `draft-ietf-oauth-identity-assertion-authz-grant` (the ID-JAG profile)

## See also

`oauth/` (the interactive `authorization_code` grant) ·
`oauth_client_credentials/` (machine to machine, no user at all) ·
`bearer_auth/` (the resource-server half on its own).
