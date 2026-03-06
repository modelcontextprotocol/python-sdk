# Stdio Server Shutdown Behavior

## Overview

When using the stdio transport, the MCP server monitors stdin for EOF (End of File)
to detect when the parent process has terminated. This ensures the server shuts down
gracefully instead of becoming an orphan process.

## How It Works

1. The server reads from stdin in a loop
2. When stdin is closed (EOF), the server detects this condition
3. The server signals shutdown by closing the read stream
4. All resources are cleaned up properly

## Parent Process Death

If the parent process (MCP client) dies unexpectedly:
- The server's stdin will be closed by the operating system
- The server detects EOF and initiates graceful shutdown
- No orphan processes remain

## Configuration

No additional configuration is required. This behavior is automatic when using
the stdio transport.

## Example

```python
from mcp.server.stdio import stdio_server

async def run_server():
    async with stdio_server() as (read_stream, write_stream):
        # Server will automatically shut down when stdin closes
        await server.run(read_stream, write_stream, init_options)
```
