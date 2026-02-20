from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("Elicit Complete Example")


@mcp.tool()
async def handle_oauth_callback(elicitation_id: str, ctx: Context[ServerSession, None]) -> str:
    """Called when OAuth flow completes out-of-band."""
    # ... process the callback ...

    # Notify the client that the elicitation is done
    await ctx.session.send_elicit_complete(elicitation_id)

    return "Authorization complete"
