from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("Dynamic Prompts")


@mcp.tool()
async def update_prompts(ctx: Context[ServerSession, None]) -> str:
    """Update available prompts and notify clients."""
    # ... modify prompts ...
    await ctx.session.send_prompt_list_changed()
    return "Prompts updated"
