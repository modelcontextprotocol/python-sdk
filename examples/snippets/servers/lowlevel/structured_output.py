"""Run from the repository root:
uv run examples/snippets/servers/lowlevel/structured_output.py
"""

import asyncio
import json

import mcp.server.stdio
from mcp import types
from mcp.server import Server, ServerRequestContext


async def handle_list_tools(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
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


async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
    """Handle tool calls with structured output."""
    if params.name == "get_weather":
        city = (params.arguments or {})["city"]

        weather_data = {
            "temperature": 22.5,
            "condition": "partly cloudy",
            "humidity": 65,
            "city": city,
        }

        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(weather_data, indent=2))],
            structured_content=weather_data,
        )

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
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(run())
