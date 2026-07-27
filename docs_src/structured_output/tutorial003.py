from typing import TypedDict

from mcp.server import MCPServer

mcp = MCPServer("Weather")


class WeatherData(TypedDict):
    temperature: float
    humidity: float
    conditions: str


@mcp.tool()
def get_weather(city: str) -> WeatherData:
    """Current weather for a city."""
    return WeatherData(temperature=16.2, humidity=0.83, conditions="Overcast")
