"""Final production MCP server with Fully Programmatic Progressive Disclosure.

This is the recommended approach for building MCP servers with progressive tool discovery.
All tool groups are defined directly in Python code with no schema.json files needed.

To run this server:
    uv run final_server.py

To test with the AI agent:
    # Terminal 1
    uv run final_server.py

    # Terminal 2
    uv run ai_agent.py
"""

import asyncio
import json
import logging
import sys
from typing import Any

import httpx

from mcp import ToolGroup
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    ContentBlock,
    TextContent,
    Tool,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# MATH TOOL IMPLEMENTATIONS
# ============================================================================


async def add(a: float, b: float) -> float:
    """Add two numbers together."""
    return a + b


async def subtract(a: float, b: float) -> float:
    """Subtract one number from another."""
    return a - b


async def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


async def divide(a: float, b: float) -> float:
    """Divide one number by another."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


# ============================================================================
# WEATHER TOOL IMPLEMENTATIONS
# ============================================================================


async def get_forecast(latitude: float, longitude: float) -> str:
    """Get weather forecast for a location using Open-Meteo API (free, no API key required).

    This tool fetches real weather data from the Open-Meteo weather API.
    Returns current conditions and 7-day forecast for the specified coordinates.
    """
    try:
        async with httpx.AsyncClient() as client:
            # Open-Meteo API endpoint - free, no authentication required
            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
                "timezone": "auto",
            }

            response = await client.get(url, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()

            # Parse current conditions
            current = data.get("current", {})
            daily = data.get("daily", {})

            forecast_text = f"""Weather Forecast for Latitude {latitude}, Longitude {longitude}

                                Current Conditions:
                                Temperature: {current.get("temperature_2m", "N/A")}°F
                                Timezone: {data.get("timezone", "N/A")}

                                7-Day Forecast:
                                """

            dates = daily.get("time", [])
            temps_max = daily.get("temperature_2m_max", [])
            temps_min = daily.get("temperature_2m_min", [])
            precip = daily.get("precipitation_sum", [])

            for i, date in enumerate(dates[:7]):
                forecast_text += f"\n{date}: "
                if i < len(temps_max) and i < len(temps_min):
                    forecast_text += f"High {temps_max[i]}°, Low {temps_min[i]}°"
                if i < len(precip):
                    if precip[i] and precip[i] > 0:
                        forecast_text += f", Precipitation {precip[i]}mm"

            return forecast_text

    except Exception as e:
        return f"Error fetching forecast: {str(e)}\n\nUsable coordinates example: 40.7128 (lat), -74.0060 (lon) for New York"


async def geocode_address(address: str) -> dict[str, Any]:
    """Convert an address or place name to geographic coordinates using Open-Meteo Geocoding API.

    This tool uses the free Open-Meteo geocoding service to convert addresses to latitude/longitude.
    Returns the first matching location with its coordinates.
    """
    try:
        async with httpx.AsyncClient() as client:
            # Open-Meteo Geocoding API - free, no authentication required
            url = "https://geocoding-api.open-meteo.com/v1/search"
            params = {
                "name": address,
                "count": 1,
                "language": "en",
            }

            response = await client.get(url, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                return {
                    "success": False,
                    "error": f"Could not find coordinates for '{address}'",
                    "hint": "Try a city name, landmark, or full address",
                }

            result = results[0]
            return {
                "success": True,
                "address": address,
                "latitude": result.get("latitude"),
                "longitude": result.get("longitude"),
                "name": result.get("name", ""),
                "country": result.get("country", ""),
                "admin1": result.get("admin1", ""),
            }

    except Exception as e:
        return {
            "success": False,
            "error": f"Geocoding error: {str(e)}",
        }


async def get_user_location() -> dict[str, Any]:
    """Get the user's current location using IP-based geolocation.

    This tool uses a free IP geolocation service to get approximate coordinates
    for the user's current location based on their IP address.
    Note: This is approximate and may not be precise.
    """
    try:
        async with httpx.AsyncClient() as client:
            # Use ip-api.com which provides free IP geolocation
            # For production, consider using a service with better accuracy
            url = "https://ipapi.co/json/"

            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            data = response.json()

            return {
                "success": True,
                "city": data.get("city"),
                "region": data.get("region"),
                "country": data.get("country_name"),
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "timezone": data.get("timezone"),
                "ip": data.get("ip"),
                "note": "Location is approximate and based on IP address",
            }

    except Exception as e:
        return {
            "success": False,
            "error": f"Location lookup error: {str(e)}",
            "note": "Try using the geocode_address tool with a specific location instead",
        }


# ============================================================================
# TOOL GROUP DEFINITIONS
# ============================================================================


# Define math group with all math tools
math_group = ToolGroup(
    name="math",
    description="Math operations: add, subtract, multiply, divide",
    tools=[
        Tool(
            name="add",
            description="Add two numbers together",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {
                        "type": "number",
                        "description": "First number",
                    },
                    "b": {
                        "type": "number",
                        "description": "Second number",
                    },
                },
                "required": ["a", "b"],
            },
        ),
        Tool(
            name="subtract",
            description="Subtract one number from another",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {
                        "type": "number",
                        "description": "Number to subtract from",
                    },
                    "b": {
                        "type": "number",
                        "description": "Number to subtract",
                    },
                },
                "required": ["a", "b"],
            },
        ),
        Tool(
            name="multiply",
            description="Multiply two numbers",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {
                        "type": "number",
                        "description": "First number",
                    },
                    "b": {
                        "type": "number",
                        "description": "Second number",
                    },
                },
                "required": ["a", "b"],
            },
        ),
        Tool(
            name="divide",
            description="Divide one number by another",
            inputSchema={
                "type": "object",
                "properties": {
                    "a": {
                        "type": "number",
                        "description": "Numerator",
                    },
                    "b": {
                        "type": "number",
                        "description": "Denominator (must not be zero)",
                    },
                },
                "required": ["a", "b"],
            },
        ),
    ],
)

# Define weather group with all weather tools
weather_group = ToolGroup(
    name="weather",
    description="Weather and location tools: get forecast, find coordinates, detect location",
    tools=[
        Tool(
            name="get_user_location",
            description="Automatically detect the user's current location using IP geolocation. Returns coordinates for weather lookups.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="geocode_address",
            description="Convert an address or place name to geographic coordinates (latitude/longitude).",
            inputSchema={
                "type": "object",
                "properties": {
                    "address": {
                        "type": "string",
                        "description": "Address, city name, or place name to geocode",
                    },
                },
                "required": ["address"],
            },
        ),
        Tool(
            name="get_forecast",
            description="Get real-time weather forecast for a location including temperature, humidity, wind, and 7-day forecast.",
            inputSchema={
                "type": "object",
                "properties": {
                    "latitude": {
                        "type": "number",
                        "description": "Latitude of the location (-90 to 90)",
                    },
                    "longitude": {
                        "type": "number",
                        "description": "Longitude of the location (-180 to 180)",
                    },
                },
                "required": ["latitude", "longitude"],
            },
        ),
    ],
)


# ============================================================================
# SERVER SETUP
# ============================================================================


def create_server() -> Server:
    """Create and configure the MCP server with progressive discovery.

    This demonstrates the recommended Option C approach:
    - Tool groups defined programmatically in Python
    - No schema.json files needed
    - All definitions and implementations together
    - One method to enable discovery
    """

    server = Server(
        name="discovery-math-weather-server",
        version="1.0.0",
        instructions="Use math or weather gateway tools to discover available operations",
    )

    # Enable discovery with the two main groups
    server.enable_discovery_with_groups(
        [
            math_group,
            weather_group,
        ]
    )

    logger.info(
        " Tool groups: %s",
        ", ".join(g.name for g in [math_group, weather_group]),
    )

    # Register list_tools handler
    # Discovery handles this automatically - no custom logic needed
    @server.list_tools()
    async def _handle_list_tools() -> list[Tool]:  # type: ignore[unused-function]
        """List available tools.

        The discovery system automatically returns gateway tools initially,
        then actual tools from loaded groups. We just return empty list here.

        Note: This is registered via decorator and intentionally not called directly.
        """
        return []

    # Register call_tool handler
    # Discovery automatically detects and handles gateway calls.
    # We just need to route actual tool calls to implementations.
    @server.call_tool()
    async def _handle_call_tool(name: str, arguments: dict[str, Any]) -> list[ContentBlock]:  # type: ignore[unused-function]
        """Execute a tool.

        Gateway handling is completely automatic. We just implement the actual tools.
        """

        logger.info(" Tool called: %s with arguments: %s", name, arguments)

        # Math tools
        if name == "add":
            result = await add(arguments["a"], arguments["b"])
            return [
                TextContent(
                    type="text",
                    text=f"{arguments['a']} + {arguments['b']} = {result}",
                )
            ]

        elif name == "subtract":
            result = await subtract(arguments["a"], arguments["b"])
            return [
                TextContent(
                    type="text",
                    text=f"{arguments['a']} - {arguments['b']} = {result}",
                )
            ]

        elif name == "multiply":
            result = await multiply(arguments["a"], arguments["b"])
            return [
                TextContent(
                    type="text",
                    text=f"{arguments['a']} × {arguments['b']} = {result}",
                )
            ]

        elif name == "divide":
            try:
                result = await divide(arguments["a"], arguments["b"])
                return [
                    TextContent(
                        type="text",
                        text=f"{arguments['a']} ÷ {arguments['b']} = {result}",
                    )
                ]
            except ValueError as e:
                return [TextContent(type="text", text=f"Error: {str(e)}")]

        # Weather/Location tools
        elif name == "get_forecast":
            result = await get_forecast(arguments["latitude"], arguments["longitude"])
            return [TextContent(type="text", text=result)]

        elif name == "geocode_address":
            result = await geocode_address(arguments["address"])
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_user_location":
            result = await get_user_location()
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


    # Register list_resources handler
    @server.list_resources()
    async def _handle_list_resources():  # type: ignore[unused-function]
        """List available resources (none for this server)."""
        return []

    return server


async def main():
    """Run the MCP server."""
    logger.info(" Starting MCP server with progressive tool discovery...")

    server = create_server()

    logger.info(" Server initialized, waiting for client connection...")

    try:
        async with stdio_server() as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options(),
            )
    except Exception:
        logger.exception("Server error")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
        sys.exit(0)
