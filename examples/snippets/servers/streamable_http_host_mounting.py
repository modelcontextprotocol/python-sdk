"""Example showing how to mount StreamableHTTP server using Host-based routing.

Run from the repository root:
    uvicorn examples.snippets.servers.streamable_http_host_mounting:app --reload
"""

import contextlib

from starlette.applications import Starlette
from starlette.routing import Host

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("MCP Host App")


@mcp.tool()
def domain_info() -> str:
    """Get domain-specific information"""
    return "This is served from mcp.acme.corp"


# The session manager must be running for the server to handle requests
@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with mcp.session_manager.run():
        yield


# Transport-specific options are passed to streamable_http_app()
app = Starlette(
    routes=[
        Host("mcp.acme.corp", app=mcp.streamable_http_app(json_response=True)),
    ],
    lifespan=lifespan,
)
