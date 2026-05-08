"""
Example showing how to use server instructions to guide tool usage.

The instructions field helps clients understand how to use your tools
together, effectively providing tool grouping/bundling/namespacing.

cd to the `examples/snippets` directory and run:
    uv run server server_instructions stdio
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

# Create server with instructions
mcp = FastMCP(
    name="Multi-Domain Server",
    instructions="""This server provides tools across multiple domains:

## Weather Tools
- get_weather: Get current weather for a location
- get_forecast: Get weather forecast

These tools work together - use get_weather for current conditions,
then get_forecast for future planning.

## Calendar Tools
- create_event: Schedule a new calendar event
- list_events: View upcoming events

Use list_events first to check availability before create_event.

## Best Practices
- Always check weather before scheduling outdoor events
- Use get_forecast to plan events 2-7 days ahead
""",
)


# Define the tools mentioned in instructions
@mcp.tool()
def get_weather(location: str) -> dict[str, Any]:
    """Get current weather for a location"""
    return {"location": location, "temperature": 72, "condition": "sunny", "humidity": 45}


@mcp.tool()
def get_forecast(location: str, days: int = 5) -> list[dict[str, Any]]:
    """Get weather forecast for upcoming days"""
    return [{"day": i, "high": 70 + i, "low": 50 + i, "condition": "partly cloudy"} for i in range(days)]


@mcp.tool()
def create_event(title: str, date: str, time: str) -> dict[str, Any]:
    """Schedule a new calendar event"""
    return {"id": "evt_123", "title": title, "date": date, "time": time, "status": "created"}


@mcp.tool()
def list_events(start_date: str, end_date: str) -> list[dict[str, Any]]:
    """View upcoming events in date range"""
    return [
        {"title": "Team Meeting", "date": start_date, "time": "10:00"},
        {"title": "Lunch with Client", "date": start_date, "time": "12:00"},
    ]
