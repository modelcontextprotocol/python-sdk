"""
FastMCP Weather Example with Structured Output

Demonstrates how to use structured output with tools to return
well-typed, validated data that clients can easily process.
"""

import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict

from pydantic import BaseModel, Field

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session as client_session

# Create server
mcp = FastMCP("Weather Service")


# Example 1: Using a Pydantic model for structured output
class WeatherData(BaseModel):
    """Structured weather data response"""

    temperature: float = Field(description="Temperature in Celsius")
    humidity: float = Field(description="Humidity percentage (0-100)")
    condition: str = Field(description="Weather condition (sunny, cloudy, rainy, etc.)")
    wind_speed: float = Field(description="Wind speed in km/h")
    location: str = Field(description="Location name")
    timestamp: datetime = Field(default_factory=datetime.now, description="Observation time")


@mcp.tool()
def get_weather(city: str) -> WeatherData:
    """Get current weather for a city with full structured data"""
    # In a real implementation, this would fetch from a weather API
    return WeatherData(temperature=22.5, humidity=65.0, condition="partly cloudy", wind_speed=12.3, location=city)


# Example 2: Using TypedDict for a simpler structure
class WeatherSummary(TypedDict):
    """Simple weather summary"""

    city: str
    temp_c: float
    description: str


@mcp.tool()
def get_weather_summary(city: str) -> WeatherSummary:
    """Get a brief weather summary for a city"""
    return WeatherSummary(city=city, temp_c=22.5, description="Partly cloudy with light breeze")


# Example 3: Using dict[str, Any] for flexible schemas
@mcp.tool()
def get_weather_metrics(cities: list[str]) -> dict[str, dict[str, float]]:
    """Get weather metrics for multiple cities

    Returns a dictionary mapping city names to their metrics
    """
    # Returns nested dictionaries with weather metrics
    return {
        city: {"temperature": 20.0 + i * 2, "humidity": 60.0 + i * 5, "pressure": 1013.0 + i * 0.5}
        for i, city in enumerate(cities)
    }


# Example 4: Using dataclass for weather alerts
@dataclass
class WeatherAlert:
    """Weather alert information"""

    severity: str  # "low", "medium", "high"
    title: str
    description: str
    affected_areas: list[str]
    valid_until: datetime


@mcp.tool()
def get_weather_alerts(region: str) -> list[WeatherAlert]:
    """Get active weather alerts for a region"""
    # In production, this would fetch real alerts
    if region.lower() == "california":
        return [
            WeatherAlert(
                severity="high",
                title="Heat Wave Warning",
                description="Temperatures expected to exceed 40 degrees",
                affected_areas=["Los Angeles", "San Diego", "Riverside"],
                valid_until=datetime(2024, 7, 15, 18, 0),
            ),
            WeatherAlert(
                severity="medium",
                title="Air Quality Advisory",
                description="Poor air quality due to wildfire smoke",
                affected_areas=["San Francisco Bay Area"],
                valid_until=datetime(2024, 7, 14, 12, 0),
            ),
        ]
    return []


# Example 5: Returning primitives with structured output
@mcp.tool()
def get_temperature(city: str, unit: str = "celsius") -> float:
    """Get just the temperature for a city

    When returning primitives as structured output,
    the result is wrapped in {"result": value}
    """
    base_temp = 22.5
    if unit.lower() == "fahrenheit":
        return base_temp * 9 / 5 + 32
    return base_temp


# Example 6: Weather statistics with nested models
class DailyStats(BaseModel):
    """Statistics for a single day"""

    high: float
    low: float
    mean: float


class WeatherStats(BaseModel):
    """Weather statistics over a period"""

    location: str
    period_days: int
    temperature: DailyStats
    humidity: DailyStats
    precipitation_mm: float = Field(description="Total precipitation in millimeters")


@mcp.tool()
def get_weather_stats(city: str, days: int = 7) -> WeatherStats:
    """Get weather statistics for the past N days"""
    return WeatherStats(
        location=city,
        period_days=days,
        temperature=DailyStats(high=28.5, low=15.2, mean=21.8),
        humidity=DailyStats(high=85.0, low=45.0, mean=65.0),
        precipitation_mm=12.4,
    )


if __name__ == "__main__":

    async def test() -> None:
        """Test the tools by calling them through the server as a client would"""
        print("Testing Weather Service Tools (via MCP protocol)\n")
        print("=" * 80)

        async with client_session(mcp._mcp_server) as client:
            # Test get_weather
            result = await client.call_tool("get_weather", {"city": "London"})
            print("\nWeather in London:")
            print(json.dumps(result.structuredContent, indent=2))

            # Test get_weather_summary
            result = await client.call_tool("get_weather_summary", {"city": "Paris"})
            print("\nWeather summary for Paris:")
            print(json.dumps(result.structuredContent, indent=2))

            # Test get_weather_metrics
            result = await client.call_tool("get_weather_metrics", {"cities": ["Tokyo", "Sydney", "Mumbai"]})
            print("\nWeather metrics:")
            print(json.dumps(result.structuredContent, indent=2))

            # Test get_weather_alerts
            result = await client.call_tool("get_weather_alerts", {"region": "California"})
            print("\nWeather alerts for California:")
            print(json.dumps(result.structuredContent, indent=2))

            # Test get_temperature
            result = await client.call_tool("get_temperature", {"city": "Berlin", "unit": "fahrenheit"})
            print("\nTemperature in Berlin:")
            print(json.dumps(result.structuredContent, indent=2))

            # Test get_weather_stats
            result = await client.call_tool("get_weather_stats", {"city": "Seattle", "days": 30})
            print("\nWeather stats for Seattle (30 days):")
            print(json.dumps(result.structuredContent, indent=2))

            # Also show the text content for comparison
            print("\nText content for last result:")
            for content in result.content:
                if content.type == "text":
                    print(content.text)

    async def print_schemas() -> None:
        """Print all tool schemas"""
        print("Tool Schemas for Weather Service\n")
        print("=" * 80)

        tools = await mcp.list_tools()
        for tool in tools:
            print(f"\nTool: {tool.name}")
            print(f"Description: {tool.description}")
            print("Input Schema:")
            print(json.dumps(tool.inputSchema, indent=2))

            if tool.outputSchema:
                print("Output Schema:")
                print(json.dumps(tool.outputSchema, indent=2))
            else:
                print("Output Schema: None (returns unstructured content)")

            print("-" * 80)

    # Check command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == "--schemas":
        asyncio.run(print_schemas())
    else:
        print("Usage:")
        print("  python weather_structured.py          # Run tool tests")
        print("  python weather_structured.py --schemas # Print tool schemas")
        print()
        asyncio.run(test())
