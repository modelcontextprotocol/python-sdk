from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server import MCPServer
from mcp.server.mcpserver import Context


class Database:
    @classmethod
    async def connect(cls) -> "Database":
        return cls()

    async def disconnect(self) -> None: ...

    def query(self) -> int:
        return 3


@dataclass
class AppContext:
    db: Database


@asynccontextmanager
async def app_lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    db = await Database.connect()
    try:
        yield AppContext(db=db)
    finally:
        await db.disconnect()


mcp = MCPServer("Bookshop", lifespan=app_lifespan)


@mcp.tool()
def count_books(genre: str, ctx: Context[AppContext]) -> str:
    """Count the books in a genre."""
    db = ctx.request_context.lifespan_context.db
    return f"{db.query()} books in {genre!r}."
