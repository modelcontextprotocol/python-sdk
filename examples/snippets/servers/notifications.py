from mcp.server.fastmcp import Context, FastMCP

mcp = FastMCP(name="Notifications Example")


@mcp.tool(description="Demonstrates logging at different levels")
async def process_data(data: str, ctx: Context) -> str:
    """Process data with comprehensive logging."""
    # Different log levels
    await ctx.debug(f"Debug: Processing '{data}'")
    await ctx.info("Info: Starting processing")
    await ctx.warning("Warning: This is experimental")
    await ctx.error("Error: (This is just a demo)")

    # Notify about resource changes
    await ctx.session.send_resource_list_changed()

    return f"Processed: {data}"
