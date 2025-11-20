# MCP Conformance Auth Client

A Python OAuth client designed for use with the MCP conformance test framework.

## Overview

This client implements OAuth authentication for MCP and is designed to work automatically with the conformance test framework without requiring user interaction. It programmatically fetches authorization URLs and extracts auth codes from redirects.

## Installation

```bash
cd examples/clients/conformance-auth-client
uv sync
```

## Usage with Conformance Tests

Run the auth conformance tests against this Python client:

```bash
# From the conformance repository
npx @modelcontextprotocol/conformance client \
  --command "uv run --directory /path/to/python-sdk/examples/clients/conformance-auth-client python -m mcp_conformance_auth_client" \
  --scenario auth/basic-dcr
```

Available auth test scenarios:

- `auth/basic-dcr` - Tests OAuth Dynamic Client Registration flow
- `auth/basic-metadata-var1` - Tests OAuth with authorization metadata

## How It Works

Unlike interactive OAuth clients that open a browser for user authentication, this client:

1. Receives the authorization URL from the OAuth provider
2. Makes an HTTP request to that URL directly (without following redirects)
3. Extracts the authorization code from the redirect response
4. Uses the code to complete the OAuth token exchange

This allows the conformance test framework's mock OAuth server to automatically provide auth codes without human interaction.

## Direct Usage

You can also run the client directly:

```bash
uv run python -m mcp_conformance_auth_client http://localhost:3000/mcp
```
