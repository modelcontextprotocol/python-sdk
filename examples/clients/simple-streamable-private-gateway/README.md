# Simple Streamable Private Gateway Example

A demonstration of how to use the MCP Python SDK as a streamable private gateway without authentication over streamable HTTP or SSE transport.

## Features

- No authentication required
- Support StreamableHTTP
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
# Example with a simple tool server
cd examples/servers/simple-tool
uv run mcp-simple-tool --transport streamable-http --port 8000

# Or use any of the other example servers
cd examples/servers/simple-resource
uv run simple-resource --transport streamable-http --port 8000
```

### 2. Run the client

```bash
uv run mcp-simple-streamable-private-gateway

# Or with custom server port
MCP_SERVER_PORT=8000 uv run mcp-simple-streamable-private-gateway
```

### 3. Use the interactive interface

The client provides several commands:

- `list` - List available tools
- `call <tool_name> [args]` - Call a tool with optional JSON arguments  
- `quit` - Exit

## Examples

### Basic tool usage

```markdown
🚀 Simple Streamable Private Gateway
Connecting to: https://localhost:8000/mcp
📡 Opening StreamableHTTP transport connection...
🤝 Initializing MCP session...
⚡ Starting session initialization...
✨ Session initialization complete!

✅ Connected to MCP server at https://localhost:8000/mcp

🎯 Interactive MCP Client
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

## Configuration

- `MCP_SERVER_PORT` - Server port (default: 8000)
- `MCP_SERVER_HOSTNAME` - Server hostname (default: 8000)

## Compatible Servers

This client works with any MCP server that doesn't require authentication, including:

- `examples/servers/simple-tool` - Basic tool server
- `examples/servers/simple-resource` - Resource server  
- `examples/servers/simple-prompt` - Prompt server
- Any custom MCP server without auth requirements
