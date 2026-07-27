from pydantic import BaseModel

from mcp.server import MCPServer

mcp = MCPServer("Weather")


class WeatherData(BaseModel):
    temperature: float
    humidity: float
    conditions: str


@mcp.tool()
def get_forecast(city: str, days: int) -> list[WeatherData]:
    """Daily forecast for a city."""
    return [WeatherData(temperature=16.2 + day, humidity=0.83, conditions="Overcast") for day in range(days)]
