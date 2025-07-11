# Simple Auth Client Example

A demonstration of how to use the MCP Python SDK with OAuth authentication using client credentials over streamable HTTP or SSE transport.
This example demonstrates integration with an authorization server that does not implement Dynamic Client Registration.

## Features

- OAuth 2.0 authentication with the `client_credentials` flow
- Support for both StreamableHTTP and SSE transports
- Interactive command-line interface

## Installation

```bash
cd examples/clients/simple-auth-client-client-credentials
uv sync --reinstall
```

## Usage

### 1. Start an MCP server with OAuth support using client credentials

```bash
# Example with mcp-simple-auth-client-credentials
cd path/to/mcp-simple-auth-client-credentials
uv run mcp-simple-auth-client-credentials --transport streamable-http --port 3001
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

The client will automatically authenticate using dummy client credentials for the demo authorization server. After completing OAuth, you can use commands:

- `list` - List available tools
- `call <tool_name> [args]` - Call a tool with optional JSON arguments
- `quit` - Exit

## Example

```markdown
🚀 Simple MCP Auth Client
Connecting to: http://localhost:8001/mcp
Transport type: streamable_http
🔗 Attempting to connect to http://localhost:8001/mcp...
📡 Opening StreamableHTTP transport connection with auth...
🤝 Initializing MCP session...
⚡ Starting session initialization...
✨ Session initialization complete!

✅ Connected to MCP server at http://localhost:8001/mcp
Session ID: ...

🎯 Interactive MCP Client
Commands:
list - List available tools
call <tool_name> [args] - Call a tool
quit - Exit the client

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
