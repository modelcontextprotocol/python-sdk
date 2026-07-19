from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError

mcp = MCPServer("Weather")

FORECASTS = {"London": "Rain.", "Cairo": "Sun."}


@mcp.tool()
def forecast(city: str) -> str:
    """Today's forecast for one city."""
    if city not in FORECASTS:
        raise ValueError(f"No forecast for {city!r}.")
    return FORECASTS[city]


@mcp.resource("weather://{city}")
def report(city: str) -> str:
    """The full report for one city."""
    if city not in FORECASTS:
        raise ResourceNotFoundError(f"No forecast for {city!r}.")
    return f"{city}: {FORECASTS[city]}"
