# Authorization

The MCP Python SDK supports **multi-protocol authorization**: OAuth 2.0, API Key, DPoP (Demonstrating Proof-of-Possession), and a Mutual TLS placeholder. Servers declare supported protocols via PRM (Protected Resource Metadata) and WWW-Authenticate; clients discover and select a protocol automatically.

## Overview

- **OAuth 2.0**: Authorization code flow with PKCE; 401 → discovery → OAuth → token → MCP. Fully supported with `OAuthClientProvider` / `OAuth2Protocol`.
- **API Key**: Send `X-API-Key` (or `Authorization: Bearer <key>` when configured). No AS required. Use `MCP_API_KEY` on the client and `--api-keys` on the server.
- **DPoP** (RFC 9449): Binds the access token to a client-held key. Use with OAuth: client sets `MCP_USE_OAUTH=1` and `MCP_DPOP_ENABLED=1`; server starts with `--dpop-enabled`.
- **Mutual TLS**: Placeholder in the examples (no client certificate validation).

Examples: [simple-auth-multiprotocol](../examples/servers/simple-auth-multiprotocol/) (server), [simple-auth-multiprotocol-client](../examples/clients/simple-auth-multiprotocol-client/) (client). See [examples/README.md](../examples/README.md) for API Key, DPoP, and mTLS running instructions.

---

For protocol implementation, migration from OAuth-only to multi-protocol, DPoP usage, and API reference, see **[Authorization: Multi-Protocol Extension](authorization-multiprotocol.md)**.
