"""
Example showing how to mount StreamableHTTP servers in Starlette applications.

Run from the repository root:
    uvicorn examples.snippets.servers.streamable_http_mounting:app --reload
"""

from starlette.applications import Starlette
from starlette.routing import Host, Mount

from mcp.server.fastmcp import FastMCP

# Basic example - mounting at root
mcp = FastMCP("My App")


@mcp.tool()
def hello() -> str:
    """A simple hello tool"""
    return "Hello from MCP!"


# Mount the StreamableHTTP server to the existing ASGI server
app = Starlette(
    routes=[
        Mount("/", app=mcp.streamable_http_app()),
    ]
)

# or dynamically mount as host
app.router.routes.append(Host("mcp.acme.corp", app=mcp.streamable_http_app()))

# Advanced example - multiple servers with path configuration
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


# Default behavior: endpoints will be at /api/mcp and /chat/mcp
default_app = Starlette(
    routes=[
        Mount("/api", app=api_mcp.streamable_http_app()),
        Mount("/chat", app=chat_mcp.streamable_http_app()),
    ]
)

# To mount at the root of each path (e.g., /api instead of /api/mcp):
# Configure streamable_http_path before mounting
api_mcp.settings.streamable_http_path = "/"
chat_mcp.settings.streamable_http_path = "/"

configured_app = Starlette(
    routes=[
        Mount("/api", app=api_mcp.streamable_http_app()),
        Mount("/chat", app=chat_mcp.streamable_http_app()),
    ]
)

# Or configure during initialization
mcp_at_root = FastMCP("My Server", streamable_http_path="/")
