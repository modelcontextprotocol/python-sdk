from mcp.server import MCPServer

mcp = MCPServer("Weather")


@mcp.tool(name="forecast")
def forecast_today(city: str) -> str:
    """Today's forecast for one city."""
    return f"{city}: Rain."


@mcp.tool(name="forecast")  # Same name. This registration is dropped.
def forecast_hourly(city: str, hours: int) -> str:
    """The next few hours for one city."""
    return f"{city}: Rain for {hours}h."
