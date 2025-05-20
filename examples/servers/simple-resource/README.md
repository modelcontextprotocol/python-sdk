# MCP Simple Resource

A simple MCP server that exposes sample text files as resources.

## Usage

Start the server using either stdio (default) or SSE transport:

```bash
# Using stdio transport (default)
uv run mcp-simple-resource

# Using SSE transport on custom port
uv run mcp-simple-resource --transport sse --port 8000
```

The server exposes some basic text file resources that can be read by clients.

## Example

Using the MCP client, you can retrieve resources like this using the STDIO transport:

```python
import asyncio
from mcp.types import AnyUrl
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def main():
    async with stdio_client(
        StdioServerParameters(command="uv", args=["run", "mcp-simple-resource"])
    ) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # List available resources
            resources = await session.list_resources()
            print(resources)

            # Get a specific resource
            resource = await session.read_resource(AnyUrl("file:///greeting.txt"))
            print(resource)


asyncio.run(main())

```
