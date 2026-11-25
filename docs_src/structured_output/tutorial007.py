import json

from pydantic import BaseModel

from mcp.server import MCPServer

mcp = MCPServer("Weather")

UPSTREAM = {"London": '{"temperature": 16.2, "conditions": "Overcast"}'}


class WeatherData(BaseModel):
    temperature: float
    humidity: float
    conditions: str


@mcp.tool()
def get_weather(city: str) -> WeatherData:
    """Current weather for a city."""
    return json.loads(UPSTREAM[city])
