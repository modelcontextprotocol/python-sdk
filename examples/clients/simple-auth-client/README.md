# Simple Auth Client Example

A demonstration of how to use the MCP Python SDK with OAuth authentication over streamable HTTP or SSE transport.

## Features

- OAuth 2.0 authentication with PKCE
- Support for both StreamableHTTP and SSE transports
- Interactive command-line interface

## Installation

```bash
cd examples/clients/simple-auth-client
uv sync --reinstall
```

## Usage

### 1. Start an MCP server with OAuth support

The simple-auth server example provides three server configurations. See [examples/servers/simple-auth/README.md](../../servers/simple-auth/README.md) for full details.

#### Option A: New Architecture (Recommended)

Separate Authorization Server and Resource Server:

```bash
# Terminal 1: Start Authorization Server on port 9000
cd examples/servers/simple-auth
uv run mcp-simple-auth-as --port=9000

# Terminal 2: Start Resource Server on port 8001
cd examples/servers/simple-auth
uv run mcp-simple-auth-rs --port=8001 --auth-server=http://localhost:9000 --transport=streamable-http
```

#### Option B: Legacy Server (Backwards Compatibility)

```bash
# Single server that acts as both AS and RS (port 8000)
cd examples/servers/simple-auth
uv run mcp-simple-auth-legacy --port=8000 --transport=streamable-http
```

### 2. Run the client

```bash
# Connect to Resource Server (new architecture, default port 8001)
MCP_SERVER_PORT=8001 uv run mcp-simple-auth-client

# Connect to Legacy Server (port 8000)
uv run mcp-simple-auth-client

# Use SSE transport
MCP_SERVER_PORT=8001 MCP_TRANSPORT_TYPE=sse uv run mcp-simple-auth-client
```

### 3. Complete OAuth flow

The client will open your browser for authentication. After completing OAuth, you can use commands:

- `list` - List available tools
- `call <tool_name> [args]` - Call a tool with optional JSON arguments
- `quit` - Exit

## Example

```markdown
🚀 Simple MCP Auth Client
Connecting to: http://localhost:8001/mcp
Transport type: streamable-http

🔗 Attempting to connect to http://localhost:8001/mcp...
📡 Opening StreamableHTTP transport connection with auth...
Opening browser for authorization: http://localhost:9000/authorize?...

✅ Connected to MCP server at http://localhost:8001/mcp

mcp> list
📋 Available tools:
1. get_time
   Description: Get the current server time.

mcp> call get_time
🔧 Tool 'get_time' result:
{"current_time": "2024-01-15T10:30:00", "timezone": "UTC", ...}

mcp> quit
```

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `MCP_SERVER_PORT` | Port number of the MCP server | `8000` |
| `MCP_TRANSPORT_TYPE` | Transport type: `streamable-http` or `sse` | `streamable-http` |
| `MCP_CLIENT_METADATA_URL` | Optional URL for client metadata (CIMD) | None |
