"""
Example showing path configuration during FastMCP initialization.

Run from the repository root:
    uvicorn examples.snippets.servers.streamable_http_path_config:app --reload
"""

from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server.fastmcp import FastMCP

# Configure streamable_http_path during initialization
# This server will mount at the root of wherever it's mounted
mcp_at_root = FastMCP("My Server", streamable_http_path="/")


@mcp_at_root.tool()
def process_data(data: str) -> str:
    """Process some data"""
    return f"Processed: {data}"


# Mount at /process - endpoints will be at /process instead of /process/mcp
app = Starlette(
    routes=[
        Mount("/process", app=mcp_at_root.streamable_http_app()),
    ]
)
