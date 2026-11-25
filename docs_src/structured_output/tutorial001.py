from mcp.server import MCPServer

mcp = MCPServer("Weather")

READINGS = {"London": 17, "Cairo": 34, "Reykjavik": 4}


@mcp.tool()
def get_temperature(city: str) -> int:
    """Current temperature in a city, in whole degrees Celsius."""
    return READINGS[city]
