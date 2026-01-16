"""Example showing how to mount multiple StreamableHTTP servers with path configuration.

Run from the repository root:
    uvicorn examples.snippets.servers.streamable_http_multiple_servers:app --reload
"""

import contextlib

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


# Create a combined lifespan to manage both session managers
@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(api_mcp.session_manager.run())
        await stack.enter_async_context(chat_mcp.session_manager.run())
        yield


# Mount the servers with transport-specific options passed to streamable_http_app()
# streamable_http_path="/" means endpoints will be at /api and /chat instead of /api/mcp and /chat/mcp
app = Starlette(
    routes=[
        Mount("/api", app=api_mcp.streamable_http_app(json_response=True, streamable_http_path="/")),
        Mount("/chat", app=chat_mcp.streamable_http_app(json_response=True, streamable_http_path="/")),
    ],
    lifespan=lifespan,
)
