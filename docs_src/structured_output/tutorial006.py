from mcp.server import MCPServer

mcp = MCPServer("Weather")

READINGS = {"London": 16.2, "Cairo": 34.1, "Reykjavik": 4.4}


@mcp.tool()
def get_temperatures(cities: list[str]) -> dict[str, float]:
    """Current temperature for each city, in degrees Celsius."""
    return {city: READINGS[city] for city in cities}
