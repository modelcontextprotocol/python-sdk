"""
Basic example showing how to mount StreamableHTTP server in Starlette.

Run from the repository root:
    uvicorn examples.snippets.servers.streamable_http_basic_mounting:app --reload
"""

import contextlib

from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server.fastmcp import FastMCP

# Create MCP server
mcp = FastMCP("My App", json_response=True)


@mcp.tool()
def hello() -> str:
    """A simple hello tool"""
    return "Hello from MCP!"


# Create a lifespan context manager to run the session manager
@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with mcp.session_manager.run():
        yield


# Mount the StreamableHTTP server to the existing ASGI server
app = Starlette(
    routes=[
        Mount("/", app=mcp.streamable_http_app()),
    ],
    lifespan=lifespan,
)
