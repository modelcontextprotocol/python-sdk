from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server import MCPServer

mcp = MCPServer("Notes")


@mcp.tool()
def add_note(text: str) -> str:
    """Save a note."""
    return f"Saved: {text}"


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


app = Starlette(
    routes=[Mount("/notes", app=mcp.streamable_http_app(streamable_http_path="/"))],
    lifespan=lifespan,
)
