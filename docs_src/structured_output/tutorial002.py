from pydantic import BaseModel, Field

from mcp.server import MCPServer

mcp = MCPServer("Weather")


class WeatherData(BaseModel):
    temperature: float = Field(description="Degrees Celsius.")
    humidity: float = Field(description="Relative humidity, 0 to 1.")
    conditions: str


@mcp.tool()
def get_weather(city: str) -> WeatherData:
    """Current weather for a city."""
    return WeatherData(temperature=16.2, humidity=0.83, conditions="Overcast")
