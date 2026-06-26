from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server import MCPServer
from mcp.server.mcpserver import Context


class Database:
    def __init__(self) -> None:
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False


@dataclass
class AppContext:
    db: Database


database = Database()


@asynccontextmanager
async def app_lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    await database.connect()
    try:
        yield AppContext(db=database)
    finally:
        await database.disconnect()


mcp = MCPServer("Bookshop", lifespan=app_lifespan)


@mcp.tool()
def database_status(ctx: Context[AppContext]) -> str:
    """Report whether the database connection is up."""
    db = ctx.request_context.lifespan_context.db
    return "connected" if db.connected else "disconnected"
