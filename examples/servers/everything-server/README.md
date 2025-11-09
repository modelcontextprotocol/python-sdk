# MCP Everything Server

A comprehensive MCP server implementing all protocol features for conformance testing.

## Overview

The Everything Server is a reference implementation that demonstrates all features of the Model Context Protocol (MCP). It is designed to be used with the [MCP Conformance Test Framework](https://github.com/modelcontextprotocol/conformance) to validate MCP client and server implementations.

## Installation

From the python-sdk root directory:

```bash
uv sync --frozen
```

## Usage

### Running the Server

Start the server with default settings (port 3001):

```bash
uv run -m mcp_everything_server
```

Or with custom options:

```bash
uv run -m mcp_everything_server --port 3001 --log-level DEBUG
```

The server will be available at: `http://localhost:3001/mcp`

### Command-Line Options

- `--port` - Port to listen on (default: 3001)
- `--log-level` - Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL (default: INFO)

## Running Conformance Tests

See the [MCP Conformance Test Framework](https://github.com/modelcontextprotocol/conformance) for instructions on running conformance tests against this server.
