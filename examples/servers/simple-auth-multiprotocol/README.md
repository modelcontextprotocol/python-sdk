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

## Options

- `--port`: RS port (default 8002).
- `--auth-server`: AS URL (default http://localhost:9000).
- `--api-keys`: Comma-separated valid API keys (default demo-api-key-12345).
- `--oauth-strict`: Enable RFC 8707 resource validation.

Mutual TLS is a placeholder (no client certificate validation).
