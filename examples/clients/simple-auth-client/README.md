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

```bash
# Example with mcp-simple-auth
cd path/to/mcp-simple-auth
uv run mcp-simple-auth --transport streamable-http --port 3001
```

### 2. Run the client

```bash
uv run mcp-simple-auth-client

# Or with custom server URL
MCP_SERVER_PORT=3001 uv run mcp-simple-auth-client

# Use SSE transport
MCP_TRANSPORT_TYPE=sse uv run mcp-simple-auth-client
```

### 3. Complete OAuth flow

The client will open your browser for authentication. After completing OAuth, you can use commands:

- `list` - List available tools
- `call <tool_name> [args]` - Call a tool with optional JSON arguments  
- `quit` - Exit

## Example

```markdown
🔐 Simple MCP Auth Client
Connecting to: http://localhost:3001

Please visit the following URL to authorize the application:
http://localhost:3001/authorize?response_type=code&client_id=...

✅ Connected to MCP server at http://localhost:3001

mcp> list
📋 Available tools:
1. echo - Echo back the input text

mcp> call echo {"text": "Hello, world!"}
🔧 Tool 'echo' result:
Hello, world!

mcp> quit
👋 Goodbye!
```

## Configuration

- `MCP_SERVER_PORT` - Server URL (default: 8000)
- `MCP_TRANSPORT_TYPE` - Transport type: `streamable_http` (default) or `sse`
