"""Example showing how to register multiple exact StreamableHTTP routes.

Run from the repository root:
    uvicorn examples.snippets.servers.streamable_http_multiple_servers:app --reload
"""

import contextlib

from starlette.applications import Starlette

from mcp.server.mcpserver import MCPServer

# Create multiple MCP servers
api_mcp = MCPServer("API Server")
chat_mcp = MCPServer("Chat Server")


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


# Register exact MCP endpoints at /api and /chat on the parent router.
app = Starlette(
    routes=[
        *api_mcp.streamable_http_routes(path="/api", json_response=True),
        *chat_mcp.streamable_http_routes(path="/chat", json_response=True),
    ],
    lifespan=lifespan,
)
