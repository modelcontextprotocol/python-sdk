# Simple Auth Multiprotocol Client

MCP client example using **MultiProtocolAuthProvider** with **API Key** and **Mutual TLS (placeholder)**.

- Uses `MultiProtocolAuthProvider` and protocol selection from server discovery (PRM / WWW-Authenticate).
- **API Key**: reads key from env `MCP_API_KEY` (default `demo-api-key-12345`), sends `X-API-Key` header.
- **Mutual TLS**: placeholder only; when selected, prints a message and exits (no client cert in this example).

## Run

1. Start the multi-protocol resource server (e.g. `simple-auth-multiprotocol` on port 8002).
2. From this directory: `uv run mcp-simple-auth-multiprotocol-client` or `uv run python -m mcp_simple_auth_multiprotocol_client`.
3. Optional: `MCP_SERVER_URL=http://localhost:8002/mcp` to override server URL.

## Commands

- `list` – list tools  
- `call get_time` – call `get_time`  
- `quit` – exit  
