# Python SDK Examples

This folder aims to provide simple examples of using the Python SDK. Please refer to the
[servers repository](https://github.com/modelcontextprotocol/servers)
for real-world servers.

## Multi-protocol auth

- **Server**: [simple-auth-multiprotocol](servers/simple-auth-multiprotocol/) — RS with OAuth, API Key, DPoP, and Mutual TLS (placeholder).

### API Key

- Use `MCP_API_KEY` on the client; start RS with `--api-keys=...` (no AS required).
- One-command test (from repo root): `MCP_AUTH_PROTOCOL=api_key ./scripts/run_phase2_multiprotocol_integration_test.sh`

### OAuth + DPoP

- Start AS and RS with `--dpop-enabled`; client: `MCP_USE_OAUTH=1 MCP_DPOP_ENABLED=1`.
- One-command test (from repo root): `./scripts/run_phase4_dpop_integration_test.sh` (use `MCP_SKIP_OAUTH=1` to skip manual OAuth step).

### Mutual TLS (placeholder)

- mTLS is a placeholder (no client cert validation). Script: `MCP_AUTH_PROTOCOL=mutual_tls ./scripts/run_phase2_multiprotocol_integration_test.sh`
- mTLS is a placeholder (no client cert validation). Script: `MCP_AUTH_PROTOCOL=mutual_tls ./scripts/run_phase2_multiprotocol_integration_test.sh`

**Client**: [simple-auth-multiprotocol-client](clients/simple-auth-multiprotocol-client/) — supports API Key (`MCP_API_KEY`), OAuth+DPoP (`MCP_USE_OAUTH=1`, `MCP_DPOP_ENABLED=1`), and mTLS placeholder.
