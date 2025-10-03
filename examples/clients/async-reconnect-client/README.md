# Async Reconnect Client Example

A demonstration of how to use the MCP Python SDK to call async tools and handle operation tokens for resuming long-running operations.

## Features

- Async tool invocation with operation tokens
- Operation status polling and result retrieval
- Support for resuming operations with existing tokens

## Installation

```bash
cd examples/clients/async-reconnect-client
uv sync --reinstall 
```

## Usage

### 1. Start an MCP server with async tools

```bash
# Example with simple-tool-async server
cd examples/servers/simple-tool-async
uv run mcp-simple-tool-async --transport streamable-http --port 8000
```

### 2. Run the client

```bash
# Connect to default endpoint
uv run mcp-async-reconnect-client

# Connect to custom endpoint
uv run mcp-async-reconnect-client --endpoint http://localhost:3001/mcp

# Resume with existing operation token
uv run mcp-async-reconnect-client --token your-operation-token-here
```

## Example

The client will call the `fetch_website` async tool and demonstrate:

1. Starting an async operation and receiving an operation token
2. Polling the operation status until completion
3. Retrieving the final result when the operation completes

```bash
$ uv run mcp-async-reconnect-client
Calling async tool...
Operation started with token: abc123...
Status: submitted
Status: working
Status: completed
Result: <html>...</html>
```

The client can be terminated during polling and resumed with the returned token, demonstrating how reconnection is supported:

```bash
$ uv run mcp-async-reconnect-client
Calling async tool...
Operation started with token: abc123...
Status: working
^C
Aborted!
$ uv run mcp-async-reconnect-client --token=abc123...
Calling async tool...
Status: completed
Result: <html>...</html>
```

## Configuration

- `--endpoint` - MCP server endpoint (default: <http://127.0.0.1:8000/mcp>)
- `--token` - Operation token to resume with (optional)

This example showcases the async tool capabilities introduced in MCP protocol version "next", allowing for long-running operations that can be resumed even if the client disconnects.
