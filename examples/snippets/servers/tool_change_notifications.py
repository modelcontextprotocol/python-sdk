from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("Dynamic Tools")


@mcp.tool()
async def register_plugin(name: str, ctx: Context[ServerSession, None]) -> str:
    """Dynamically register a new tool and notify the client."""
    # ... register the plugin's tools ...

    # Notify the client that the tool list has changed
    await ctx.session.send_tool_list_changed()

    return f"Plugin '{name}' registered"
