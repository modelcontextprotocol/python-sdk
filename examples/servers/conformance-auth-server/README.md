# MCP Conformance Auth Server

A minimal MCP server with OAuth authentication for conformance testing.

This server is designed to work with the MCP conformance test framework's server auth tests.

## Features

- Bearer token authentication with validation
- Protected Resource Metadata (PRM) endpoint at `/.well-known/oauth-protected-resource`
- Simple tools for testing authenticated calls

## Usage

### Prerequisites

You need to set the `MCP_CONFORMANCE_AUTH_SERVER_URL` environment variable to point to the authorization server that will issue tokens.

### Running the server

```bash
# From the python-sdk root directory
cd examples/servers/conformance-auth-server

# Install dependencies
uv sync

# Run the server
MCP_CONFORMANCE_AUTH_SERVER_URL=http://localhost:3000 uv run mcp-conformance-auth-server
```

### With conformance tests

```bash
# Run the conformance test with this server
npx @modelcontextprotocol/conformance server --suite auth \
  --auth-command 'uv run --directory examples/servers/conformance-auth-server mcp-conformance-auth-server'
```

## Configuration

- `MCP_CONFORMANCE_AUTH_SERVER_URL` (required): URL of the authorization server
- `PORT` (optional): Server port (default: 3001)
- `--log-level`: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

## Token Validation

The server validates Bearer tokens using OAuth 2.0 Token Introspection (RFC 7662).
It discovers the introspection endpoint from the authorization server's metadata
and calls it to validate each token.

This approach ensures the server properly integrates with the authorization server
rather than relying on hardcoded token patterns.
