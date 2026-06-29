"""Basic example showing how to mount StreamableHTTP server in Starlette.

Run from the repository root:
    uvicorn examples.snippets.servers.streamable_http_basic_mounting:app --reload
"""

import contextlib

from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("My App")


@mcp.tool()
def hello() -> str:
    """A simple hello tool"""
    return "Hello from MCP!"


# The session manager must be running for the transport to handle requests
@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with mcp.session_manager.run():
        yield


# Transport-specific options are passed to streamable_http_app()
app = Starlette(
    routes=[
        Mount("/", app=mcp.streamable_http_app(json_response=True)),
    ],
    lifespan=lifespan,
)
