"""Example showing exact-path StreamableHTTP registration in Starlette.

Run from the repository root:
    uvicorn examples.snippets.servers.streamable_http_path_config:app --reload
"""

import contextlib

from starlette.applications import Starlette

from mcp.server.mcpserver import MCPServer

# Create a simple MCPServer server
mcp_at_root = MCPServer("My Server")


@mcp_at_root.tool()
def process_data(data: str) -> str:
    """Process some data"""
    return f"Processed: {data}"


routes = mcp_at_root.streamable_http_routes(path="/process", json_response=True)


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with mcp_at_root.session_manager.run():
        yield


# Register the MCP endpoint directly at /process with no redirect to /process/
app = Starlette(routes=routes, lifespan=lifespan)
