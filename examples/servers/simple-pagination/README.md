# MCP Simple Pagination

A simple MCP server demonstrating pagination for tools, resources, and prompts using cursor-based pagination.

## Usage

Start the server using either stdio (default) or SSE transport:

```bash
# Using stdio transport (default)
uv run mcp-simple-pagination

# Using SSE transport on custom port
uv run mcp-simple-pagination --transport sse --port 8000
```

The server exposes:

- 25 tools (paginated, 5 per page)
- 30 resources (paginated, 10 per page)
- 20 prompts (paginated, 7 per page)

Each paginated list returns a `nextCursor` when more pages are available. Use this cursor in subsequent requests to retrieve the next page.

## Example

Using the MCP client, you can retrieve paginated items like this using the STDIO transport:

```python
import asyncio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def main():
    async with stdio_client(
        StdioServerParameters(command="uv", args=["run", "mcp-simple-pagination"])
    ) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Get first page of tools
            tools_page1 = await session.list_tools()
            print(f"First page: {len(tools_page1.tools)} tools")
            print(f"Next cursor: {tools_page1.nextCursor}")

            # Get second page using cursor
            if tools_page1.nextCursor:
                tools_page2 = await session.list_tools(cursor=tools_page1.nextCursor)
                print(f"Second page: {len(tools_page2.tools)} tools")

            # Similarly for resources
            resources_page1 = await session.list_resources()
            print(f"First page: {len(resources_page1.resources)} resources")

            # And for prompts
            prompts_page1 = await session.list_prompts()
            print(f"First page: {len(prompts_page1.prompts)} prompts")


asyncio.run(main())
```

## Pagination Details

The server uses simple numeric indices as cursors for demonstration purposes. In production scenarios, you might use:

- Database offsets or row IDs
- Timestamps for time-based pagination
- Opaque tokens encoding pagination state

The pagination implementation demonstrates:

- Handling `None` cursor for the first page
- Returning `nextCursor` when more data exists
- Gracefully handling invalid cursors
- Different page sizes for different resource types
