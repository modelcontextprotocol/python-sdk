# Simple Tool Async Example

A simple MCP server that demonstrates async tool execution with operation tokens and long-running operations.

## Usage

Start the server using either stdio (default) or streamable-http transport:

```bash
# Using stdio transport (default)
uv run mcp-simple-tool-async

# Using streamable-http transport on custom port
uv run mcp-simple-tool-async --transport streamable-http --port 8000
```

The server exposes an async tool named "fetch_website" that accepts one required argument:

- `url`: The URL of the website to fetch

The tool runs asynchronously with a 5-second delay to simulate a long-running operation, making it useful for testing async tool capabilities.

## Example

Using the MCP client with protocol version "next", you can use the async tool like this:

```python
import asyncio
from mcp import ClientSession, types
from mcp.client.streamable_http import streamablehttp_client


async def main():
    async with streamablehttp_client("http://127.0.0.1:8000/mcp") as (read, write, _):
        async with ClientSession(read, write, protocol_version="next") as session:
            await session.initialize()

            # Call the async tool
            result = await session.call_tool("fetch_website", {"url": "https://example.com"})
            
            # Get operation token
            token = result.operation.token
            print(f"Operation started with token: {token}")

            # Poll for completion
            while True:
                status = await session.get_operation_status(token)
                if status.status == "completed":
                    final_result = await session.get_operation_result(token)
                    print(f"Result: {final_result.result.content[0].text}")
                    break
                await asyncio.sleep(0.5)


asyncio.run(main())
```
