"""Example showing path configuration when mounting MCPServer.

Run from the repository root:
    uvicorn examples.snippets.servers.streamable_http_path_config:app --reload
"""

from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server.mcpserver import MCPServer

# Create a simple MCPServer server
mcp_at_root = MCPServer("My Server")


@mcp_at_root.tool()
def process_data(data: str) -> str:
    """Process some data"""
    return f"Processed: {data}"


# Mount at /process with streamable_http_path="/" so the endpoint is /process (not /process/mcp)
# Transport-specific options like json_response are passed to streamable_http_app()
app = Starlette(
    routes=[
        Mount(
            "/process",
            app=mcp_at_root.streamable_http_app(json_response=True, streamable_http_path="/"),
        ),
    ]
)
