"""Run from the repository root:
uv run examples/snippets/servers/lowlevel/lifespan.py
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import mcp.server.stdio
from mcp import types
from mcp.server.context import ServerRequestContext
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


async def handle_list_tools(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    """List available tools."""
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="query_db",
                description="Query the database",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "SQL query to execute"}},
                    "required": ["query"],
                },
            )
        ]
    )


async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
    """Handle database query tool call."""
    if params.name != "query_db":
        raise ValueError(f"Unknown tool: {params.name}")

    # Access lifespan context from the ctx parameter
    db = ctx.lifespan_context["db"]

    # Execute query
    results = await db.query((params.arguments or {})["query"])

    return types.CallToolResult(content=[types.TextContent(type="text", text=f"Query results: {results}")])


# Pass lifespan to server
server = Server(
    "example-server",
    lifespan=server_lifespan,
    on_list_tools=handle_list_tools,
    on_call_tool=handle_call_tool,
)


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
    asyncio.run(run())
