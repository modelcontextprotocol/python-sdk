"""Example showing structured output with tools."""

from pydantic import BaseModel, Field

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Structured Output Example")


# Using Pydantic models for rich structured data
class WeatherData(BaseModel):
    """Weather information structure."""

    temperature: float = Field(description="Temperature in Celsius")
    humidity: float = Field(description="Humidity percentage")
    condition: str
    wind_speed: float


@mcp.tool()
def get_weather(city: str) -> WeatherData:
    """Get weather for a city - returns structured data."""
    # Simulated weather data
    return WeatherData(
        temperature=72.5,
        humidity=45.0,
        condition="sunny",
        wind_speed=5.2,
    )
