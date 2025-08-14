"""
Example showing how to mount StreamableHTTP server using Host-based routing.

Run from the repository root:
    uvicorn examples.snippets.servers.streamable_http_host_mounting:app --reload
"""

from starlette.applications import Starlette
from starlette.routing import Host

from mcp.server.fastmcp import FastMCP

# Create MCP server
mcp = FastMCP("MCP Host App")


@mcp.tool()
def domain_info() -> str:
    """Get domain-specific information"""
    return "This is served from mcp.acme.corp"


# Mount using Host-based routing
app = Starlette(
    routes=[
        Host("mcp.acme.corp", app=mcp.streamable_http_app()),
    ]
)
