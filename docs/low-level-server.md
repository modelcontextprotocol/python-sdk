# Low-Level Server

For more control, you can use the low-level server implementation directly. This gives you full access to the protocol and allows you to customize every aspect of your server, including lifecycle management through the lifespan API.

## Lifespan

<!-- snippet-source examples/snippets/servers/lowlevel/lifespan.py -->
```python
"""
Run from the repository root:
    uv run examples/snippets/servers/lowlevel/lifespan.py
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions


# Mock database class for example
class Database:
    """Mock database class for example."""

    @classmethod
    async def connect(cls) -> "Database":
        """Connect to database."""
        print("Database connected")
        return cls()

    async def disconnect(self) -> None:
        """Disconnect from database."""
        print("Database disconnected")

    async def query(self, query_str: str) -> list[dict[str, str]]:
        """Execute a query."""
        # Simulate database query
        return [{"id": "1", "name": "Example", "query": query_str}]


@asynccontextmanager
async def server_lifespan(_server: Server) -> AsyncIterator[dict[str, Any]]:
    """Manage server startup and shutdown lifecycle."""
    # Initialize resources on startup
    db = await Database.connect()
    try:
        yield {"db": db}
    finally:
        # Clean up on shutdown
        await db.disconnect()


# Pass lifespan to server
server = Server("example-server", lifespan=server_lifespan)


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools."""
    return [
        types.Tool(
            name="query_db",
            description="Query the database",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "SQL query to execute"}},
                "required": ["query"],
            },
        )
    ]


@server.call_tool()
async def query_db(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    """Handle database query tool call."""
    if name != "query_db":
        raise ValueError(f"Unknown tool: {name}")

    # Access lifespan context
    ctx = server.request_context
    db = ctx.lifespan_context["db"]

    # Execute query
    results = await db.query(arguments["query"])

    return [types.TextContent(type="text", text=f"Query results: {results}")]


async def run():
    """Run the server with lifespan management."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="example-server",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
```

_Full example: [examples/snippets/servers/lowlevel/lifespan.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/lowlevel/lifespan.py)_
<!-- /snippet-source -->

The lifespan API provides:

- A way to initialize resources when the server starts and clean them up when it stops
- Access to initialized resources through the request context in handlers
- Type-safe context passing between lifespan and request handlers

## Basic Example

<!-- snippet-source examples/snippets/servers/lowlevel/basic.py -->
```python
"""
Run from the repository root:
uv run examples/snippets/servers/lowlevel/basic.py
"""

import asyncio

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

# Create a server instance
server = Server("example-server")


@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    """List available prompts."""
    return [
        types.Prompt(
            name="example-prompt",
            description="An example prompt template",
            arguments=[types.PromptArgument(name="arg1", description="Example argument", required=True)],
        )
    ]


@server.get_prompt()
async def handle_get_prompt(name: str, arguments: dict[str, str] | None) -> types.GetPromptResult:
    """Get a specific prompt by name."""
    if name != "example-prompt":
        raise ValueError(f"Unknown prompt: {name}")

    arg1_value = (arguments or {}).get("arg1", "default")

    return types.GetPromptResult(
        description="Example prompt",
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(type="text", text=f"Example prompt text with argument: {arg1_value}"),
            )
        ],
    )


async def run():
    """Run the basic low-level server."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="example",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(run())
```

_Full example: [examples/snippets/servers/lowlevel/basic.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/lowlevel/basic.py)_
<!-- /snippet-source -->

Caution: The `uv run mcp run` and `uv run mcp dev` tool doesn't support low-level server.

## Structured Output Support

The low-level server supports structured output for tools, allowing you to return both human-readable content and machine-readable structured data. Tools can define an `outputSchema` to validate their structured output:

<!-- snippet-source examples/snippets/servers/lowlevel/structured_output.py -->
```python
"""
Run from the repository root:
    uv run examples/snippets/servers/lowlevel/structured_output.py
"""

import asyncio
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

server = Server("example-server")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """List available tools with structured output schemas."""
    return [
        types.Tool(
            name="get_weather",
            description="Get current weather for a city",
            inputSchema={
                "type": "object",
                "properties": {"city": {"type": "string", "description": "City name"}},
                "required": ["city"],
            },
            outputSchema={
                "type": "object",
                "properties": {
                    "temperature": {"type": "number", "description": "Temperature in Celsius"},
                    "condition": {"type": "string", "description": "Weather condition"},
                    "humidity": {"type": "number", "description": "Humidity percentage"},
                    "city": {"type": "string", "description": "City name"},
                },
                "required": ["temperature", "condition", "humidity", "city"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Handle tool calls with structured output."""
    if name == "get_weather":
        city = arguments["city"]

        # Simulated weather data - in production, call a weather API
        weather_data = {
            "temperature": 22.5,
            "condition": "partly cloudy",
            "humidity": 65,
            "city": city,  # Include the requested city
        }

        # low-level server will validate structured output against the tool's
        # output schema, and additionally serialize it into a TextContent block
        # for backwards compatibility with pre-2025-06-18 clients.
        return weather_data
    else:
        raise ValueError(f"Unknown tool: {name}")


async def run():
    """Run the structured output server."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="structured-output-example",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(run())
```

_Full example: [examples/snippets/servers/lowlevel/structured_output.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/lowlevel/structured_output.py)_
<!-- /snippet-source -->

Tools can return data in four ways:

1. **Content only**: Return a list of content blocks (default behavior before spec revision 2025-06-18)
2. **Structured data only**: Return a dictionary that will be serialized to JSON (Introduced in spec revision 2025-06-18)
3. **Both**: Return a tuple of (content, structured_data) preferred option to use for backwards compatibility
4. **Direct CallToolResult**: Return `CallToolResult` directly for full control (including `_meta` field)

When an `outputSchema` is defined, the server automatically validates the structured output against the schema. This ensures type safety and helps catch errors early.

### Returning CallToolResult Directly

For full control over the response including the `_meta` field (for passing data to client applications without exposing it to the model), return `CallToolResult` directly:

<!-- snippet-source examples/snippets/servers/lowlevel/direct_call_tool_result.py -->
```python
"""
Run from the repository root:
    uv run examples/snippets/servers/lowlevel/direct_call_tool_result.py
"""

import asyncio
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

server = Server("example-server")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """List available tools."""
    return [
        types.Tool(
            name="advanced_tool",
            description="Tool with full control including _meta field",
            inputSchema={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    """Handle tool calls by returning CallToolResult directly."""
    if name == "advanced_tool":
        message = str(arguments.get("message", ""))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Processed: {message}")],
            structuredContent={"result": "success", "message": message},
            _meta={"hidden": "data for client applications only"},
        )

    raise ValueError(f"Unknown tool: {name}")


async def run():
    """Run the server."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="example",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(run())
```

_Full example: [examples/snippets/servers/lowlevel/direct_call_tool_result.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/lowlevel/direct_call_tool_result.py)_
<!-- /snippet-source -->

**Note:** When returning `CallToolResult`, you bypass the automatic content/structured conversion. You must construct the complete response yourself.

## Pagination (Advanced)

For servers that need to handle large datasets, the low-level server provides paginated versions of list operations. This is an optional optimization - most servers won't need pagination unless they're dealing with hundreds or thousands of items.

### Server-side Implementation

<!-- snippet-source examples/snippets/servers/pagination_example.py -->
```python
"""
Example of implementing pagination with MCP server decorators.
"""

from pydantic import AnyUrl

import mcp.types as types
from mcp.server.lowlevel import Server

# Initialize the server
server = Server("paginated-server")

# Sample data to paginate
ITEMS = [f"Item {i}" for i in range(1, 101)]  # 100 items


@server.list_resources()
async def list_resources_paginated(request: types.ListResourcesRequest) -> types.ListResourcesResult:
    """List resources with pagination support."""
    page_size = 10

    # Extract cursor from request params
    cursor = request.params.cursor if request.params is not None else None

    # Parse cursor to get offset
    start = 0 if cursor is None else int(cursor)
    end = start + page_size

    # Get page of resources
    page_items = [
        types.Resource(uri=AnyUrl(f"resource://items/{item}"), name=item, description=f"Description for {item}")
        for item in ITEMS[start:end]
    ]

    # Determine next cursor
    next_cursor = str(end) if end < len(ITEMS) else None

    return types.ListResourcesResult(resources=page_items, nextCursor=next_cursor)
```

_Full example: [examples/snippets/servers/pagination_example.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/pagination_example.py)_
<!-- /snippet-source -->

### Client-side Consumption

<!-- snippet-source examples/snippets/clients/pagination_client.py -->
```python
"""
Example of consuming paginated MCP endpoints from a client.
"""

import asyncio

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import PaginatedRequestParams, Resource


async def list_all_resources() -> None:
    """Fetch all resources using pagination."""
    async with stdio_client(StdioServerParameters(command="uv", args=["run", "mcp-simple-pagination"])) as (
        read,
        write,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()

            all_resources: list[Resource] = []
            cursor = None

            while True:
                # Fetch a page of resources
                result = await session.list_resources(params=PaginatedRequestParams(cursor=cursor))
                all_resources.extend(result.resources)

                print(f"Fetched {len(result.resources)} resources")

                # Check if there are more pages
                if result.nextCursor:
                    cursor = result.nextCursor
                else:
                    break

            print(f"Total resources: {len(all_resources)}")


if __name__ == "__main__":
    asyncio.run(list_all_resources())
```

_Full example: [examples/snippets/clients/pagination_client.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/clients/pagination_client.py)_
<!-- /snippet-source -->

### Key Points

- **Cursors are opaque strings** - the server defines the format (numeric offsets, timestamps, etc.)
- **Return `nextCursor=None`** when there are no more pages
- **Backward compatible** - clients that don't support pagination will still work (they'll just get the first page)
- **Flexible page sizes** - Each endpoint can define its own page size based on data characteristics

See the [simple-pagination example](examples/servers/simple-pagination) for a complete implementation.
