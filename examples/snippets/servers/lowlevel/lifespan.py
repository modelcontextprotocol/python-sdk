"""Run from the repository root:
uv run examples/snippets/servers/lowlevel/lifespan.py
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TypedDict

import mcp.server.stdio
from mcp import types
from mcp.server import Server, ServerRequestContext


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


class AppContext(TypedDict):
    db: Database


@asynccontextmanager
async def server_lifespan(_server: Server[AppContext]) -> AsyncIterator[AppContext]:
    """Manage server startup and shutdown lifecycle."""
    db = await Database.connect()
    try:
        yield {"db": db}
    finally:
        await db.disconnect()


async def handle_list_tools(
    ctx: ServerRequestContext[AppContext], params: types.PaginatedRequestParams | None
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


async def handle_call_tool(
    ctx: ServerRequestContext[AppContext], params: types.CallToolRequestParams
) -> types.CallToolResult:
    """Handle database query tool call."""
    if params.name != "query_db":
        raise ValueError(f"Unknown tool: {params.name}")

    db = ctx.lifespan_context["db"]
    results = await db.query((params.arguments or {})["query"])

    return types.CallToolResult(content=[types.TextContent(type="text", text=f"Query results: {results}")])


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
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
