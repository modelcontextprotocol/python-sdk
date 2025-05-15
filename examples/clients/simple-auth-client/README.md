# Simple OAuth Client Example

This example demonstrates how to create an MCP client that connects to an OAuth-protected server using the Python SDK's OAuth client support.

## Overview

This client connects to the [simple-auth server](../../servers/simple-auth/) and demonstrates:
- OAuth 2.0 client authentication with PKCE
- Token storage and management
- Handling the OAuth authorization flow
- Making authenticated requests to protected tools

## Prerequisites

1. **Set up the simple-auth server first**:
   - Follow the instructions in [../../servers/simple-auth/README.md](../../servers/simple-auth/README.md)
   - Make sure the server is running on `http://localhost:8000`

2. **Create a GitHub OAuth App** (if not done already):
   - Go to GitHub Settings > Developer settings > OAuth Apps > New OAuth App
   - Application name: "Simple MCP Auth Demo"
   - Homepage URL: `http://localhost:8000`
   - Authorization callback URL: `http://localhost:8080/callback`
   - Note: The client uses port 8080 for its callback, while the server uses 8000

## Installation

```bash
# Install dependencies with uv
uv install

# Or install in development mode with dev dependencies
uv install --dev
```

## Running the Client

```bash
# Basic usage - will start OAuth flow if not authenticated
uv run mcp-simple-auth-client

# Specify custom server URL
uv run mcp-simple-auth-client --server-url http://localhost:8000

# Specify custom callback port (if port 8080 is in use)
uv run mcp-simple-auth-client --callback-port 8081

# Use file-based token storage instead of in-memory
uv run mcp-simple-auth-client --use-file-storage

# Run with debug logging
uv run mcp-simple-auth-client --debug
```

## How It Works

1. **First Run**: If no tokens are stored, the client will:
   - Start a local HTTP server to handle the OAuth callback
   - Open your default browser to the GitHub authorization page
   - Wait for you to authorize the application
   - Exchange the authorization code for tokens
   - Save the tokens for future use

2. **Subsequent Runs**: The client will:
   - Load existing tokens from storage
   - Use them to authenticate with the server
   - Automatically refresh tokens if needed

3. **Making Requests**: Once authenticated, the client can:
   - Call the `get_user_profile` tool
   - Display the GitHub user information

## Example Output

```
$ uv run mcp-simple-auth-client
Starting OAuth client...
No existing tokens found. Starting OAuth flow...
Opening authorization URL in browser...
Starting callback server on http://localhost:8080...
Waiting for OAuth callback...
Authorization successful!
Connecting to MCP server...
Calling get_user_profile tool...

GitHub User Profile:
{
  "login": "username",
  "id": 12345,
  "name": "John Doe",
  "email": "john@example.com",
  "bio": "Developer",
  "public_repos": 42,
  "followers": 100,
  "following": 50
}

Done!
```

## OAuth Flow

```
Client                    Browser                    GitHub                    MCP Server
  |                         |                          |                          |
  |-- Opens auth URL ------>|                          |                          |
  |                         |-- User authorizes ------>|                          |
  |                         |                          |<-- Auth code ------------|
  |<-- Callback ------------|                          |                          |
  |                         |                          |                          |
  |-- Exchange code for tokens ------------------------>|                          |
  |<-- Access token -----------------------------------|                          |
  |                         |                          |                          |
  |-- Authenticated request -------------------------------------------------------->|
  |<-- Protected resource -----------------------------------------------------------|
```

## Development

```bash
# Run linting
uv run ruff check .

# Run type checking
uv run pyright

# Run with development dependencies
uv run --dev pytest
```

## Troubleshooting

**Client fails to connect:**
- Make sure the server is running: `uv run mcp-simple-auth` in the server directory
- Check that the server URL is correct (default: http://localhost:8000)
- Verify OAuth configuration matches between client and server

**OAuth flow fails:**
- Ensure GitHub OAuth app callback URL matches the client's callback URL
- Check that no other service is using the callback port (default: 8080)
- Make sure your browser allows opening localhost URLs

**Token issues:**
- Delete stored tokens to restart the OAuth flow: `rm oauth_*.json`
- Check that the server is configured with valid GitHub OAuth credentials

## Security Notes

- Tokens are stored locally in files or memory
- The local callback server only runs during the OAuth flow
- Consider using HTTPS in production environments
- Implement proper token encryption for sensitive applications