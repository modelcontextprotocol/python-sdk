from mcp.server.mcpserver import Context, MCPServer

mcp = MCPServer(name="Notifications Example")


@mcp.tool()
async def process_data(data: str, ctx: Context) -> str:
    """Process data with logging."""
    # Different log levels
    await ctx.debug(f"Debug: Processing '{data}'")  # pyright: ignore[reportDeprecated]
    await ctx.info("Info: Starting processing")  # pyright: ignore[reportDeprecated]
    await ctx.warning("Warning: This is experimental")  # pyright: ignore[reportDeprecated]
    await ctx.error("Error: (This is just a demo)")  # pyright: ignore[reportDeprecated]

    # Notify about resource changes
    await ctx.session.send_resource_list_changed()

    return f"Processed: {data}"
