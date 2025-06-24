# MCP OAuth Authentication Demo

This example demonstrates OAuth 2.0 authentication with the Model Context Protocol as an OAuth 2.0 Resource Server using the `client_credentials` token exchange, with
an Authorization Server that does not support Dynamic Client Registration.

---

## Setup Requirements

**Create a Discord OAuth App:**

- Go to the [Discord Developer Portal](https://discord.com/developers/applications) > New Application
- Navigate to Settings > OAuth2
- Note down your **Client ID**
- Reset your **Client Secret** and note it down

**Set environment variables:**

```bash
export MCP_DISCORD_CLIENT_ID="your_client_id_here"
export MCP_DISCORD_CLIENT_SECRET="your_client_secret_here"
```

---

## Running the Servers

### Step 1: Start Authorization Server

```bash
# Navigate to the simple-auth-client-credentials directory
cd examples/servers/simple-auth-client-credentials

# Start Authorization Server on port 9000
uv run mcp-simple-auth-as --port=9000
```

**What it provides:**

- OAuth 2.0 flows (registration, authorization, token exchange)
- Discord OAuth integration for user authentication

---

### Step 2: Start Resource Server (MCP Server)

```bash
# In another terminal, navigate to the simple-auth-client-credentials directory
cd examples/servers/simple-auth-client-credentials

# Start Resource Server on port 8001, connected to Authorization Server
uv run mcp-simple-auth-rs --port=8001 --auth-server=http://localhost:9000 --transport=streamable-http
```

### Step 3: Test with Client

```bash
cd examples/clients/simple-auth-client-client-credentials
# Start client with streamable HTTP
MCP_SERVER_PORT=8001 MCP_TRANSPORT_TYPE=streamable_http uv run mcp-simple-auth-client-client-credentials
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
