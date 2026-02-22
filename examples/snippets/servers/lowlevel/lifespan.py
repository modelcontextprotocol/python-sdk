"""Run from the repository root:
uv run examples/snippets/servers/lowlevel/lifespan.py
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TypedDict
from uuid import uuid4

import mcp.server.stdio
from mcp import types
from mcp.server import Server, ServerRequestContext


# Mock database class for example
class Database:
    """Mock database class for example."""

    connections: int = 0

    @classmethod
    async def connect(cls) -> "Database":
        """Connect to database."""
        cls.connections += 1
        print(f"Database connected (total connections: {cls.connections})")
        return cls()

    async def disconnect(self) -> None:
        """Disconnect from database."""
        self.connections -= 1
        print(f"Database disconnected (total connections: {self.connections})")

    async def query(self, query_str: str) -> list[dict[str, str]]:
        """Execute a query."""
        # Simulate database query
        return [{"id": "1", "name": "Example", "query": query_str}]


class ServerContext(TypedDict):
    """Server-level context (shared across all clients)."""

    db: Database


class SessionContext(TypedDict):
    """Session-level context (per-client connection)."""

    session_id: str


@asynccontextmanager
async def server_lifespan(_server: Server) -> AsyncIterator[ServerContext]:
    """Manage server startup and shutdown lifecycle.

    This runs ONCE when the server process starts, before any clients connect.
    Use this for resources that should be shared across all client connections:
    - Database connection pools
    - Machine learning models
    - Shared caches
    - Global configuration
    """
    print("[SERVER LIFESPAN] Starting server...")
    db = await Database.connect()
    try:
        print("[SERVER LIFESPAN] Server started, database connected")
        yield {"db": db}
    finally:
        await db.disconnect()
        print("[SERVER LIFESPAN] Server stopped, database disconnected")


@asynccontextmanager
async def session_lifespan(_server: Server) -> AsyncIterator[SessionContext]:
    """Manage per-client session lifecycle.

    This runs FOR EACH CLIENT that connects to the server.
    Use this for resources that are specific to a single client connection:
    - User authentication context
    - Per-client transaction state
    - Client-specific caches
    - Session identifiers
    """
    session_id = str(uuid4())
    print(f"[SESSION LIFESPAN] Session {session_id} started")
    try:
        yield {"session_id": session_id}
    finally:
        print(f"[SESSION LIFESPAN] Session {session_id} stopped")


async def handle_list_tools(
    ctx: ServerRequestContext[ServerContext, SessionContext],
    params: types.PaginatedRequestParams | None,
) -> types.ListToolsResult:
    """List available tools."""
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="query_db",
                description="Query the database (uses shared server connection)",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "SQL query to execute"}},
                    "required": ["query"],
                },
            ),
            types.Tool(
                name="get_session_info",
                description="Get information about the current session",
                input_schema={
                    "type": "object",
                    "properties": {},
                },
            ),
        ]
    )


async def handle_call_tool(
    ctx: ServerRequestContext[ServerContext, SessionContext],
    params: types.CallToolRequestParams,
) -> types.CallToolResult:
    """Handle tool calls."""
    if params.name == "query_db":
        # Access server-level resource (shared database connection)
        db = ctx.server_lifespan_context["db"]
        results = await db.query((params.arguments or {})["query"])

        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=f"Query results (session {ctx.session_lifespan_context['session_id']}): {results}",
                )
            ]
        )

    if params.name == "get_session_info":
        # Access session-level resource (session ID)
        session_id = ctx.session_lifespan_context["session_id"]

        return types.CallToolResult(content=[types.TextContent(type="text", text=f"Your session ID: {session_id}")])

    raise ValueError(f"Unknown tool: {params.name}")


# Create server with BOTH server and session lifespans
server = Server(
    "example-server",
    server_lifespan=server_lifespan,  # Runs once at server startup
    session_lifespan=session_lifespan,  # Runs per-client connection
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
