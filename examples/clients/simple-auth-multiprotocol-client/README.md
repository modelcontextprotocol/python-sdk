# Simple Auth Multiprotocol Client

MCP client example using **MultiProtocolAuthProvider** with **API Key** and **Mutual TLS (placeholder)**.

- Uses `MultiProtocolAuthProvider` and protocol selection from server discovery (PRM / WWW-Authenticate).
- **API Key**: reads key from env `MCP_API_KEY` (default `demo-api-key-12345`), sends `X-API-Key` header.
- **Mutual TLS**: placeholder only; when selected, prints a message and exits (no client cert in this example).

## Run

1. Start the multi-protocol resource server (e.g. `simple-auth-multiprotocol` on port 8002).
2. From this directory: `uv run mcp-simple-auth-multiprotocol-client` or `uv run python -m mcp_simple_auth_multiprotocol_client`.
3. Optional: `MCP_SERVER_URL=http://localhost:8002/mcp` to override server URL.

## Running with API Key

When the server supports API Key (e.g. `simple-auth-multiprotocol` with `--api-keys`), set:

- **`MCP_API_KEY`** – your API key (e.g. `demo-api-key-12345`). The client sends it as `X-API-Key`.
- **`MCP_SERVER_URL`** – optional; default is `http://localhost:8002/mcp` when using the default client config.

Example (server on port 8002, no OAuth/AS required):

```bash
MCP_SERVER_URL=http://localhost:8002/mcp MCP_API_KEY=demo-api-key-12345 uv run mcp-simple-auth-multiprotocol-client
```

**One-command test** from repo root:  
`MCP_PHASE2_PROTOCOL=api_key ./scripts/run_phase2_multiprotocol_integration_test.sh`  
starts the resource server and this client with API Key; at `mcp>` run `list`, `call get_time {}`, `quit`.

## Running with OAuth + DPoP

When the server has DPoP enabled (`--dpop-enabled`), use OAuth and DPoP together:

- **`MCP_USE_OAUTH=1`** – enable OAuth (required for DPoP).
- **`MCP_DPOP_ENABLED=1`** – send DPoP-bound access tokens (DPoP proof in each request).

Example (server on port 8002 with DPoP, AS on 9000):

```bash
MCP_SERVER_URL=http://localhost:8002/mcp MCP_USE_OAUTH=1 MCP_DPOP_ENABLED=1 uv run mcp-simple-auth-multiprotocol-client
```

Complete OAuth in the browser; then at `mcp>` run `list`, `call get_time {}`, `quit`. Server logs should show "Authentication successful with DPoP".

**One-command test** from repo root:  
`./scripts/run_phase4_dpop_integration_test.sh` — starts AS and RS with DPoP, then runs this client (OAuth+DPoP). Use `MCP_SKIP_OAUTH=1` to run only the automated curl tests and skip the manual client step.

## Running with Mutual TLS (placeholder)

Mutual TLS is a **placeholder** in this example: the client registers the `mutual_tls` protocol but does **not** perform client certificate authentication. Selecting mTLS will show a "not implemented" style message.

- **`MCP_PHASE2_PROTOCOL=mutual_tls`** (with the phase2 script) runs this client in mTLS mode; the client will start but mTLS auth is not implemented.

**One-command test** from repo root:  
`MCP_PHASE2_PROTOCOL=mutual_tls ./scripts/run_phase2_multiprotocol_integration_test.sh`

## Commands

- `list` – list tools  
- `call get_time` – call `get_time`  
- `quit` – exit  
