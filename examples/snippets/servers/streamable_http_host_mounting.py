"""
Example showing how to mount StreamableHTTP server using Host-based routing.

Run from the repository root:
    uvicorn examples.snippets.servers.streamable_http_host_mounting:app --reload
"""

import contextlib

from starlette.applications import Starlette
from starlette.routing import Host

from mcp.server.fastmcp import FastMCP

# Create MCP server
mcp = FastMCP("MCP Host App", stateless_http=True)


@mcp.tool()
def domain_info() -> str:
    """Get domain-specific information"""
    return "This is served from mcp.acme.corp"


# Create lifespan context manager to initialize the session manager
@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    """Context manager for managing MCP session manager lifecycle."""
    async with mcp.session_manager.run():
        yield


# Mount using Host-based routing
app = Starlette(
    routes=[
        Host("mcp.acme.corp", app=mcp.streamable_http_app()),
    ],
    lifespan=lifespan,
)
