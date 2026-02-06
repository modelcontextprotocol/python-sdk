# simple-auth-multiprotocol

MCP Resource Server example that supports **OAuth 2.0** (introspection), **API Key** (X-API-Key or Bearer \<key\>), and **Mutual TLS** (placeholder).

- Uses `MultiProtocolAuthBackend` with `OAuthTokenVerifier`, `APIKeyVerifier`, and a Mutual TLS placeholder verifier.
- PRM and `RequireAuthMiddleware` use `auth_protocols` (oauth2, api_key, mutual_tls), `default_protocol`, and `protocol_preferences`.
- Serves `/.well-known/authorization_servers` for unified discovery.

## Run

1. Start the Authorization Server (same as simple-auth):  
   From `examples/servers/simple-auth`: `uv run mcp-simple-auth-as --port=9000`

2. Start this Resource Server:  
   From this directory: `uv run mcp-simple-auth-multiprotocol-rs --port=8002 --auth-server=http://localhost:9000`

3. Use OAuth (e.g. simple-auth-client) or API Key:  
   - OAuth: same as simple-auth (401 → discovery → OAuth → token → MCP).  
   - API Key: set header `X-API-Key: demo-api-key-12345` or `Authorization: Bearer demo-api-key-12345` (default key).  
   Custom keys: `--api-keys=key1,key2`.

## Running with API Key only

You can run the Resource Server **without** the Authorization Server when using API Key authentication:

1. **Start the Resource Server** (from this directory):

   ```bash
   uv run mcp-simple-auth-multiprotocol-rs --port=8002 --api-keys=demo-api-key-12345
   ```

2. **Run the client** from `examples/clients/simple-auth-multiprotocol-client`:

   ```bash
   MCP_SERVER_URL=http://localhost:8002/mcp MCP_API_KEY=demo-api-key-12345 uv run mcp-simple-auth-multiprotocol-client
   ```

3. At the `mcp>` prompt, run `list`, `call get_time {}`, then `quit`.

**One-command verification** (from repo root):  
`MCP_AUTH_PROTOCOL=api_key ./scripts/run_phase2_multiprotocol_integration_test.sh`  
This starts the RS, then the client with API Key; complete the session with `list`, `call get_time {}`, `quit`.

## Running with DPoP (OAuth + DPoP)

DPoP (Demonstrating Proof-of-Possession, RFC 9449) binds the access token to a client-held key. Use it together with OAuth.

1. **Start the Authorization Server** (from `examples/servers/simple-auth`):  
   `uv run mcp-simple-auth-as --port=9000`

2. **Start this Resource Server with DPoP enabled** (from this directory):

   ```bash
   uv run mcp-simple-auth-multiprotocol-rs --port=8002 --auth-server=http://localhost:9000 --api-keys=demo-api-key-12345 --dpop-enabled
   ```

3. **Run the client** with OAuth and DPoP from `examples/clients/simple-auth-multiprotocol-client`:

   ```bash
   MCP_SERVER_URL=http://localhost:8002/mcp MCP_USE_OAUTH=1 MCP_DPOP_ENABLED=1 uv run mcp-simple-auth-multiprotocol-client
   ```

   Complete OAuth in the browser, then at `mcp>` run `list`, `call get_time {}`, `quit`. Server logs should show "Authentication successful with DPoP".

**One-command verification** (from repo root):  
`./scripts/run_phase4_dpop_integration_test.sh` — starts AS and RS (with `--dpop-enabled`), runs automated DPoP tests, then optionally the OAuth+DPoP client (use `MCP_SKIP_OAUTH=1` to skip the manual OAuth step).

## Running with Mutual TLS (placeholder)

Mutual TLS is a **placeholder** in this example: the server accepts the `mutual_tls` protocol in PRM/discovery but does **not** perform client certificate validation. Selecting mTLS in the client will show a "not implemented" style message.

- **Server**: No extra flags; `auth_protocols` already includes `mutual_tls`.
- **Client** (from repo root):  
  `MCP_AUTH_PROTOCOL=mutual_tls ./scripts/run_phase2_multiprotocol_integration_test.sh`  
  The client will start but mTLS authentication is not implemented in this example.

## Options

- `--port`: RS port (default 8002).
- `--auth-server`: AS URL (default <http://localhost:9000>).
- `--api-keys`: Comma-separated valid API keys (default demo-api-key-12345).
- `--oauth-strict`: Enable RFC 8707 resource validation.
- `--dpop-enabled`: Enable DPoP proof verification (RFC 9449); use with OAuth.

Mutual TLS is a placeholder (no client certificate validation).
