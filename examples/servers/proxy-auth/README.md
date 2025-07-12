# OAuth Proxy Server

This is a minimal OAuth proxy server example for the MCP Python SDK that demonstrates how to create a transparent OAuth proxy for existing OAuth providers.

## Installation

```bash
# Navigate to the proxy-auth directory
cd examples/servers/proxy-auth

# Install the package in development mode
uv add -e .
```

## Configuration

The servers can be configured using either:

1. **Command-line arguments** (take precedence when provided)
2. **Environment variables** (loaded from `.env` file when present)

Example `.env` file:

```env
# Auth Server Configuration
AUTH_SERVER_HOST=localhost
AUTH_SERVER_PORT=9000
AUTH_SERVER_URL=http://localhost:9000

# Resource Server Configuration
RESOURCE_SERVER_HOST=localhost
RESOURCE_SERVER_PORT=8001
RESOURCE_SERVER_URL=http://localhost:8001

# Combo Server Configuration
COMBO_SERVER_HOST=localhost
COMBO_SERVER_PORT=8000

# OAuth Provider Configuration
UPSTREAM_AUTHORIZE=https://github.com/login/oauth/authorize
UPSTREAM_TOKEN=https://github.com/login/oauth/access_token
CLIENT_ID=your-client-id
CLIENT_SECRET=your-client-secret
DEFAULT_SCOPE=openid
```

## Running the Servers

The example consists of three server components that can be run using the project scripts defined in pyproject.toml:

### Step 1: Start Authorization Server

```bash
# Start Authorization Server on port 9000
uv run mcp-proxy-auth-as --port=9000

# Or rely on environment variables from .env file
uv run mcp-proxy-auth-as
```

**What it provides:**

- OAuth 2.0 flows (authorization, token exchange)
- Token introspection endpoint for Resource Servers (`/introspect`)
- Client registration endpoint (`/register`)

### Step 2: Start Resource Server (MCP Server)

```bash
# In another terminal, start Resource Server on port 8001
uv run mcp-proxy-auth-rs --port=8001 --auth-server=http://localhost:9000 --transport=streamable-http

# Or rely on environment variables from .env file
uv run mcp-proxy-auth-rs
```

### Step 3: Alternatively, Run Combined Server

For simpler testing, you can run a combined proxy server that handles both authentication and resource access:

```bash
# Run the combined proxy server on port 8000
uv run mcp-proxy-auth-combo --port=8000 --transport=streamable-http

# Or rely on environment variables from .env file
uv run mcp-proxy-auth-combo
```

## How It Works

The proxy OAuth server acts as a transparent proxy between:

1. Client applications requesting OAuth tokens
2. Upstream OAuth providers (like GitHub, Google, etc.)

This allows MCP servers to leverage existing OAuth providers without implementing their own authentication systems.

The server code is organized in the `proxy_auth` package for better modularity.

```text
```
