"""
Example showing ASGI route mounting with lifespan context management.

From the repository root:
    cd examples/snippets/servers
    uv run streamable_uvicorn_lifespan.py
"""

import contextlib

from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server.fastmcp import FastMCP

# Create MCP server
mcp = FastMCP(name="My App", stateless_http=True)


@mcp.tool()
def ping() -> str:
    """A simple ping tool"""
    return "pong"


# lifespan for managing the session manager
@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    """Gather any session managers for startup/shutdown.
    See streamable_starlette_mount.py for example of multiple mcp managers.
    """
    async with mcp.session_manager.run():
        yield


"""Create the Starlette app and mount the MCP server.
lifespan ensures the session manager is started/stopped with the app.
session_manager references must only be made after streamable_http_app()
"""
app = Starlette(
    routes=[
        # Mounted at /mcp
        Mount("/", app=mcp.streamable_http_app()),
    ],
    lifespan=lifespan,
)

if __name__ == "__main__":
    import uvicorn

    """Attach to another ASGI server LIFO
    ASGI chain: Uvicorn -> Starlette -> FastMCP
    Route: http://0.0.0.0:8000/mcp
    """
    uvicorn.run(app, host="0.0.0.0", port=8000)
