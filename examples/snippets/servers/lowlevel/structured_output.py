"""Run from the repository root:
uv run examples/snippets/servers/lowlevel/structured_output.py
"""

import asyncio
from typing import Any

import mcp.server.stdio
from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions


async def handle_list_tools(
    ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    """List available tools with structured output schemas."""
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="get_weather",
                description="Get current weather for a city",
                input_schema={
                    "type": "object",
                    "properties": {"city": {"type": "string", "description": "City name"}},
                    "required": ["city"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "temperature": {"type": "number", "description": "Temperature in Celsius"},
                        "condition": {"type": "string", "description": "Weather condition"},
                        "humidity": {"type": "number", "description": "Humidity percentage"},
                        "city": {"type": "string", "description": "City name"},
                    },
                    "required": ["temperature", "condition", "humidity", "city"],
                },
            )
        ]
    )


async def handle_call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
    """Handle tool calls with structured output."""
    if params.name == "get_weather":
        city = (params.arguments or {})["city"]

        # Simulated weather data - in production, call a weather API
        weather_data = {
            "temperature": 22.5,
            "condition": "partly cloudy",
            "humidity": 65,
            "city": city,  # Include the requested city
        }

        # Return as CallToolResult with structured_content for structured output.
        # The low-level server will validate structured output against the tool's
        # output schema, and additionally serialize it into a TextContent block
        # for backwards compatibility with pre-2025-06-18 clients.
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=str(weather_data))],
            structured_content=weather_data,
        )
    else:
        raise ValueError(f"Unknown tool: {params.name}")


server = Server(
    "example-server",
    on_list_tools=handle_list_tools,
    on_call_tool=handle_call_tool,
)


async def run():
    """Run the structured output server."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="structured-output-example",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(run())
