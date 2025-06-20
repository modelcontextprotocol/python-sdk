# MCP OAuth Authentication Demo

This example demonstrates OAuth 2.0 authentication with the Model Context Protocol using **separate Authorization Server (AS) and Resource Server (RS)** to comply with the new RFC 9728 specification.

---

## Setup Requirements

**Create a GitHub OAuth App:**
- Go to GitHub Settings > Developer settings > OAuth Apps > New OAuth App
- **Authorization callback URL:** `http://localhost:9000/github/callback`
- Note down your **Client ID** and **Client Secret**

**Set environment variables:**
```bash
export MCP_GITHUB_CLIENT_ID="your_client_id_here"  
export MCP_GITHUB_CLIENT_SECRET="your_client_secret_here"
```

---

## Running the Servers

### Step 1: Start Authorization Server

```bash
# Navigate to the simple-auth directory
cd examples/servers/simple-auth

# Start Authorization Server on port 9000
python -m mcp_simple_auth.auth_server --port=9000
```

**What it provides:**
- OAuth 2.0 flows (registration, authorization, token exchange)
- GitHub OAuth integration for user authentication
- Token introspection endpoint for Resource Servers (`/introspect`)
- User data proxy endpoint (`/github/user`)

---

### Step 2: Start Resource Server (MCP Server)

```bash
# In another terminal, navigate to the simple-auth directory
cd examples/servers/simple-auth

# Start Resource Server on port 8001, connected to Authorization Server
python -m mcp_simple_auth.server --port=8001 --auth-server=http://localhost:9000  --transport=streamable-http

# With RFC 8707 strict resource validation (recommended for production)
python -m mcp_simple_auth.server --port=8001 --auth-server=http://localhost:9000  --transport=streamable-http --oauth-strict
```

**OAuth Strict Mode (`--oauth-strict`):**
- Enables RFC 8707 resource indicator validation
- Ensures tokens are only accepted if they were issued for this specific resource server
- Prevents token misuse across different services
- Recommended for production environments where security is critical


### Step 3: Test with Client

```bash
cd examples/clients/simple-auth-client
# Start client with streamable HTTP  
MCP_SERVER_PORT=8001 MCP_TRANSPORT_TYPE=streamable_http python -m mcp_simple_auth_client.main
```


## How It Works

### RFC 9728 Discovery

**Client → Resource Server:**
```bash
curl http://localhost:8001/.well-known/oauth-protected-resource
```
```json
{
  "resource": "http://localhost:8001",
  "authorization_servers": ["http://localhost:9000"]
}
```

**Client → Authorization Server:**
```bash
curl http://localhost:9000/.well-known/oauth-authorization-server
```
```json
{
  "issuer": "http://localhost:9000",
  "authorization_endpoint": "http://localhost:9000/authorize",
  "token_endpoint": "http://localhost:9000/token"
}
```

## Legacy MCP Server as Authorization Server (Backwards Compatibility)

For backwards compatibility with older MCP implementations, a legacy server is provided that acts as an Authorization Server (following the old spec where MCP servers could optionally provide OAuth):

### Running the Legacy Server

```bash
# Start legacy authorization server on port 8002
python -m mcp_simple_auth.legacy_as_server --port=8002
```

**Differences from the new architecture:**
- **MCP server acts as AS:** The MCP server itself provides OAuth endpoints (old spec behavior)
- **No separate RS:** The server handles both authentication and MCP tools
- **Local token validation:** Tokens are validated internally without introspection
- **No RFC 9728 support:** Does not provide `/.well-known/oauth-protected-resource`
- **Direct OAuth discovery:** OAuth metadata is at the MCP server's URL

### Testing with Legacy Server

```bash
# Test with client (will automatically fall back to legacy discovery)
MCP_SERVER_PORT=8002 MCP_TRANSPORT_TYPE=streamable_http python -m mcp_simple_auth_client.main
```

The client will:
1. Try RFC 9728 discovery at `/.well-known/oauth-protected-resource` (404 on legacy server)
2. Fall back to direct OAuth discovery at `/.well-known/oauth-authorization-server` 
3. Complete authentication with the MCP server acting as its own AS

This ensures existing MCP servers (which could optionally act as Authorization Servers under the old spec) continue to work while the ecosystem transitions to the new architecture where MCP servers are Resource Servers only.

## Manual Testing

### Test Discovery
```bash
# Test Resource Server discovery endpoint (new architecture)
curl -v http://localhost:8001/.well-known/oauth-protected-resource

# Test Authorization Server metadata
curl -v http://localhost:9000/.well-known/oauth-authorization-server
```

### Test Token Introspection
```bash
# After getting a token through OAuth flow:
curl -X POST http://localhost:9000/introspect \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "token=your_access_token"
```
