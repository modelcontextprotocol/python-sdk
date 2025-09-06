"""
Example showing how to mount multiple StreamableHTTP servers with path configuration.

Run from the repository root:
    uvicorn examples.snippets.servers.streamable_http_multiple_servers:app --reload
"""

from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.server.fastmcp import FastMCP

# Create multiple MCP servers
api_mcp = FastMCP("API Server")
chat_mcp = FastMCP("Chat Server")


@api_mcp.tool()
def api_status() -> str:
    """Get API status"""
    return "API is running"


@chat_mcp.tool()
def send_message(message: str) -> str:
    """Send a chat message"""
    return f"Message sent: {message}"


# Configure servers to mount at the root of each path
# This means endpoints will be at /api and /chat instead of /api/mcp and /chat/mcp
api_mcp.settings.streamable_http_path = "/"
chat_mcp.settings.streamable_http_path = "/"

# Mount the servers
app = Starlette(
    routes=[
        Mount("/api", app=api_mcp.streamable_http_app()),
        Mount("/chat", app=chat_mcp.streamable_http_app()),
    ]
)
