"""
Run from the repository root:
    uv run examples/snippets/servers/lowlevel/direct_call_tool_result.py
"""

import asyncio
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

server = Server("example-server")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """List available tools."""
    return [
        types.Tool(
            name="advanced_tool",
            description="Tool with full control including _meta field",
            inputSchema={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    """Handle tool calls by returning CallToolResult directly."""
    if name == "advanced_tool":
        message = str(arguments.get("message", ""))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Processed: {message}")],
            structuredContent={"result": "success", "message": message},
            _meta={"hidden": "data for client applications only"},
        )

    raise ValueError(f"Unknown tool: {name}")


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
