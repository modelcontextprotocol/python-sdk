"""Run from the repository root:
uv run examples/snippets/servers/lowlevel/direct_call_tool_result.py
"""

import asyncio

import mcp.server.stdio
from mcp import types
from mcp.server import Server, ServerRequestContext


async def handle_list_tools(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
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


async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
    """Handle tool calls by returning CallToolResult directly."""
    if params.name == "advanced_tool":
        message = (params.arguments or {}).get("message", "")
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
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(run())
