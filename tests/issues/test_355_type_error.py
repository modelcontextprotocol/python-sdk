from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.mcpserver import Context, MCPServer


class Database:
    @classmethod
    async def connect(cls):  # pragma: no cover
        return cls()

    async def disconnect(self):  # pragma: no cover
        pass

    def query(self):  # pragma: no cover
        return "Hello, World!"


mcp = MCPServer("My App")


@dataclass
class AppContext:
    db: Database


@asynccontextmanager
async def app_lifespan(server: MCPServer) -> AsyncIterator[AppContext]:  # pragma: no cover
    db = await Database.connect()
    try:
        yield AppContext(db=db)
    finally:
        await db.disconnect()


mcp = MCPServer("My App", lifespan=app_lifespan)


@mcp.tool()
def query_db(ctx: Context[AppContext]) -> str:  # pragma: no cover
    """Tool that uses initialized resources"""
    db = ctx.request_context.lifespan_context.db
    return db.query()
