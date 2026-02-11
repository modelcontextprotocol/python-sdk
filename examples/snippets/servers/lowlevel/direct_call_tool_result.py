"""Run from the repository root:
uv run examples/snippets/servers/lowlevel/direct_call_tool_result.py
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
    """List available tools."""
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="advanced_tool",
                description="Tool with full control including _meta field",
                input_schema={
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
            )
        ]
    )


async def handle_call_tool(
    ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
) -> types.CallToolResult:
    """Handle tool calls by returning CallToolResult directly."""
    if params.name == "advanced_tool":
        message = str((params.arguments or {}).get("message", ""))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Processed: {message}")],
            structured_content={"result": "success", "message": message},
            _meta={"hidden": "data for client applications only"},
        )

    raise ValueError(f"Unknown tool: {params.name}")


server = Server(
    "example-server",
    on_list_tools=handle_list_tools,
    on_call_tool=handle_call_tool,
)


async def run():
    """Run the server."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="example",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(run())
