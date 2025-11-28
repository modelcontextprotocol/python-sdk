# Simple Streamable Private Gateway Example

A demonstration of how to use the MCP Python SDK as a streamable private gateway without authentication over streamable HTTP or SSE transport with custom extensions for private gateway connectivity (SNI hostname support).

## Features

- No authentication required
- Supports both StreamableHTTP and SSE transports
- Custom extensions for private gateway (SNI hostname) - **Both transports**
- Interactive command-line interface
- Tool calling

## Installation

```bash
cd examples/clients/simple-streamable-private-gateway
uv sync --reinstall 
```

## Usage

### 1. Start an MCP server without authentication

You can use any MCP server that doesn't require authentication. For example:

```bash
# Example with StreamableHTTP transport
cd examples/servers/simple-tool
uv run mcp-simple-tool --transport streamable-http --port 8081

# Or with SSE transport
cd examples/servers/simple-tool
uv run mcp-simple-tool --transport sse --port 8081

# Or use any of the other example servers
cd examples/servers/simple-resource
uv run simple-resource --transport streamable-http --port 8081
```

### 2. Run the client

```bash
# Default: StreamableHTTP transport
uv run mcp-simple-streamable-private-gateway

# Or with SSE transport
MCP_TRANSPORT_TYPE=sse uv run mcp-simple-streamable-private-gateway

# Or with custom server port and hostname
MCP_SERVER_PORT=8081 MCP_SERVER_HOSTNAME=mcp.deepwiki.com uv run mcp-simple-streamable-private-gateway
```

### 3. Use the interactive interface

The client provides several commands:

- `list` - List available tools
- `call <tool_name> [args]` - Call a tool with optional JSON arguments  
- `quit` - Exit

## Examples

### StreamableHTTP Transport

```markdown
🚀 Simple Streamable Private Gateway
Connecting to: https://localhost:8081/mcp
Server hostname: mcp.deepwiki.com
Transport type: streamable-http
📡 Opening StreamableHTTP transport connection with extensions...
🤝 Initializing MCP session...
⚡ Starting session initialization...
✨ Session initialization complete!

✅ Connected to MCP server at https://localhost:8081/mcp
Session ID: abc123...

🎯 Interactive MCP Client (Private Gateway)
Commands:
  list - List available tools
  call <tool_name> [args] - Call a tool
  quit - Exit the client

mcp> list
📋 Available tools:
1. echo
   Description: Echo back the input text

mcp> call echo {"text": "Hello, world!"}
🔧 Tool 'echo' result:
Hello, world!

mcp> quit
👋 Goodbye!
```

### SSE Transport

```markdown
🚀 Simple Streamable Private Gateway
Connecting to: https://localhost:8081/sse
Server hostname: mcp.deepwiki.com
Transport type: sse
📡 Opening SSE transport connection with extensions...
🤝 Initializing MCP session...
⚡ Starting session initialization...
✨ Session initialization complete!

✅ Connected to MCP server at https://localhost:8081/sse

🎯 Interactive MCP Client (Private Gateway)
Commands:
  list - List available tools
  call <tool_name> [args] - Call a tool
  quit - Exit the client

mcp> list
📋 Available tools:
1. echo
   Description: Echo back the input text

mcp> quit
👋 Goodbye!
```

## Configuration

Environment variables:

- `MCP_SERVER_PORT` - Server port (default: 8081)
- `MCP_SERVER_HOSTNAME` - Server hostname for SNI (default: mcp.deepwiki.com)
- `MCP_TRANSPORT_TYPE` - Transport type: `streamable-http` or `sse` (default: streamable-http)
