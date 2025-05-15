# Simple MCP Server with GitHub OAuth Authentication

This is a simple example of an MCP server with GitHub OAuth authentication. It demonstrates the essential components needed for OAuth integration with just a single tool.

This is just an example of a server that uses auth, an official GitHub mcp server is [here](https://github.com/github/github-mcp-server)

## Overview

This simple demo to show to set up a server with:
- GitHub OAuth2 authorization flow
- Single tool: `get_user_profile` to retrieve GitHub user information


## Prerequisites

1. Create a GitHub OAuth App:
   - Go to GitHub Settings > Developer settings > OAuth Apps > New OAuth App
   - Application name: Any name (e.g., "Simple MCP Auth Demo")
   - Homepage URL: `http://localhost:8000`
   - Authorization callback URL: `http://localhost:8000/github/callback`
   - Click "Register application"
   - Note down your Client ID and Client Secret

## Required Environment Variables

You MUST set these environment variables before running the server:

```bash
export MCP_GITHUB_GITHUB_CLIENT_ID="your_client_id_here"
export MCP_GITHUB_GITHUB_CLIENT_SECRET="your_client_secret_here"
```

The server will not start without these environment variables properly set.


## Running the Server

```bash
# Set environment variables first (see above)

# Run the server
uv run mcp-simple-auth
```

The server will start on `http://localhost:8000`.

### Transport Options

This server supports multiple transport protocols that can run on the same port:

#### SSE (Server-Sent Events) - Default
```bash
uv run mcp-simple-auth
# or explicitly:
uv run mcp-simple-auth --transport sse
```

SSE transport provides endpoint:
- `/sse`

#### Streamable HTTP
```bash
uv run mcp-simple-auth --transport streamable-http
```

Streamable HTTP transport provides endpoint:
- `/mcp`


This ensures backward compatibility without needing multiple server instances. When using SSE transport (`--transport sse`), only the `/sse` endpoint is available.

## Available Tool

### get_user_profile

The only tool in this simple example. Returns the authenticated user's GitHub profile information.

**Required scope**: `user`

**Returns**: GitHub user profile data including username, email, bio, etc.


## Troubleshooting

If the server fails to start, check:
1. Environment variables `MCP_GITHUB_GITHUB_CLIENT_ID` and `MCP_GITHUB_GITHUB_CLIENT_SECRET` are set
2. The GitHub OAuth app callback URL matches `http://localhost:8000/github/callback`
3. No other service is using port 8000
4. The transport specified is valid (`sse` or `streamable-http`)

You can use [Inspector](https://github.com/modelcontextprotocol/inspector) to test Auth