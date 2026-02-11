#!/usr/bin/env python3
"""Example low-level MCP server demonstrating structured output support.

This example shows how to use the low-level server API to return
structured data from tools, with automatic validation against output
schemas.
"""

import asyncio
import random
from datetime import datetime

import mcp.server.stdio
from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions


async def handle_list_tools(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    """List available tools with their schemas."""
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="get_weather",
                description="Get weather information (simulated)",
                input_schema={
                    "type": "object",
                    "properties": {"city": {"type": "string", "description": "City name"}},
                    "required": ["city"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "temperature": {"type": "number"},
                        "conditions": {"type": "string"},
                        "humidity": {"type": "integer", "minimum": 0, "maximum": 100},
                        "wind_speed": {"type": "number"},
                        "timestamp": {"type": "string", "format": "date-time"},
                    },
                    "required": ["temperature", "conditions", "humidity", "wind_speed", "timestamp"],
                },
            ),
        ]
    )


async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
    """Handle tool call with structured output."""

    if params.name == "get_weather":
        # city = (params.arguments or {})["city"]  # Would be used with real weather API

        # Simulate weather data (in production, call a real weather API)
        weather_conditions = ["sunny", "cloudy", "rainy", "partly cloudy", "foggy"]

        weather_data = {
            "temperature": round(random.uniform(0, 35), 1),
            "conditions": random.choice(weather_conditions),
            "humidity": random.randint(30, 90),
            "wind_speed": round(random.uniform(0, 30), 1),
            "timestamp": datetime.now().isoformat(),
        }

        # Return structured data as CallToolResult
        # The low-level server will serialize this to JSON content automatically
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=str(weather_data))],
            structured_content=weather_data,
        )

    else:
        raise ValueError(f"Unknown tool: {params.name}")


# Create low-level server instance
server = Server(
    "structured-output-lowlevel-example",
    on_list_tools=handle_list_tools,
    on_call_tool=handle_call_tool,
)


async def run():
    """Run the low-level server using stdio transport."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="structured-output-lowlevel-example",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(run())
