# Simple Auth Client Example

This example demonstrates how to use the MCP Python SDK to create a client that connects to an MCP server using OAuth authentication over streamable HTTP transport.

## Features

- OAuth 2.0 authentication with PKCE
- Streamable HTTP transport  
- Interactive command-line interface
- Tool listing and execution

## Prerequisites

1. Python 3.9 or higher
2. An MCP server that supports OAuth authentication (like `mcp-simple-auth`)
3. uv for dependency management

## Installation

```bash
cd examples/clients/simple-auth-client
uv install
```

## Usage

### 1. Start the Auth Server

First, start the MCP auth server in another terminal:

```bash
cd path/to/mcp-simple-auth
uv run mcp-simple-auth --transport streamable-http --port 3001
```

### 2. Run the Client

```bash
# Run the client
uv run mcp-simple-auth-client

# Or with custom server URL
MCP_SERVER_URL=http://localhost:3001 uv run mcp-simple-auth-client
```

### 3. Authentication Flow

1. The client will attempt to connect to the server
2. If authentication is required, the client will open your default browser 
3. Complete the OAuth flow in the browser
4. Return to the client - it should now be connected

### 4. Interactive Commands

Once connected, you can use these commands:

- `list` - List available tools from the server
- `call <tool_name> [args]` - Call a tool with optional JSON arguments
- `quit` - Exit the client

### Example Session

```
=� Simple MCP Auth Client
Connecting to: http://localhost:3001

Please visit the following URL to authorize the application:
http://localhost:3001/authorize?response_type=code&client_id=...

 Connected to MCP server at http://localhost:3001
Session ID: abc123

<� Interactive MCP Client
Commands:
  list - List available tools
  call <tool_name> [args] - Call a tool
  quit - Exit the client

mcp> list

=� Available tools:
1. echo
   Description: Echo back the input text

mcp> call echo {"text": "Hello, world!"}

=' Tool 'echo' result:
Hello, world!

mcp> quit
=K Goodbye!
```

## Configuration

You can customize the client behavior with environment variables:

- `MCP_SERVER_URL` - Server URL (default: http://localhost:3001)
- `AUTH_CODE` - Authorization code for completing OAuth flow

## Implementation Details

This example shows how to:

1. **Create an OAuth provider** - Implement the `OAuthClientProvider` protocol
2. **Use streamable HTTP transport** - Connect using the `streamablehttp_client` context manager  
3. **Handle authentication** - Manage OAuth flow including browser redirect
4. **Interactive tool usage** - List and call tools from the command line

The key components are:

- `SimpleOAuthProvider` - Minimal OAuth provider implementation
- `SimpleAuthClient` - Main client class that handles connection and tool operations
- Interactive loop for user commands

## Error Handling

The client handles common error scenarios:

- Server connection failures
- Authentication errors  
- Invalid tool calls
- Network timeouts

All errors are displayed with helpful messages to guide debugging.