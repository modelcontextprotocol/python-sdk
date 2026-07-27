from mcp.server import MCPServer

mcp = MCPServer("Weather")


@mcp.tool(structured_output=False)
def weather_report(city: str) -> str:
    """A human-readable weather report for a city."""
    return f"{city}: 17 degrees, overcast, light rain easing by evening."
