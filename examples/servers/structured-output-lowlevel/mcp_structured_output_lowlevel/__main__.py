#!/usr/bin/env python3
"""Example low-level MCP server demonstrating structured output support.

This example shows how to use the low-level server API to return
structured data from tools.
"""

import asyncio
import json
import random
from datetime import datetime

import mcp.server.stdio
from mcp import types
from mcp.server import Server, ServerRequestContext


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
        # Simulate weather data (in production, call a real weather API)
        weather_conditions = ["sunny", "cloudy", "rainy", "partly cloudy", "foggy"]

        weather_data = {
            "temperature": round(random.uniform(0, 35), 1),
            "conditions": random.choice(weather_conditions),
            "humidity": random.randint(30, 90),
            "wind_speed": round(random.uniform(0, 30), 1),
            "timestamp": datetime.now().isoformat(),
        }

        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(weather_data, indent=2))],
            structured_content=weather_data,
        )

    raise ValueError(f"Unknown tool: {params.name}")


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
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(run())
