from mcp.server.mcpserver import MCPServer

mcp = MCPServer("Unit Converter", subscriptions=False)


@mcp.tool()
def km_to_miles(km: float) -> float:
    """Convert kilometres to miles."""
    return km * 0.621371
