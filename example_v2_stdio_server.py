"""Minimal V2 low-level MCP server over stdio. Run with: uv run --frozen python example_v2_stdio_server.py"""

import anyio

from mcp_v2.context import RequestContext
from mcp_v2.server import LowLevelServer
from mcp_v2.transport.stdio import run_stdio
from mcp_v2.types.content import TextContent
from mcp_v2.types.json_rpc import JSONRPCRequest
from mcp_v2.types.tools import CallToolRequestParams, CallToolResult, JsonSchema, ListToolsResult, Tool

server = LowLevelServer(name="example-v2-stdio", version="0.1.0")


@server.request_handler("tools/list")
async def list_tools(ctx: RequestContext, request: JSONRPCRequest) -> ListToolsResult:
    return ListToolsResult(
        tools=[
            Tool(
                name="greet",
                description="Returns a greeting",
                input_schema=JsonSchema(properties={"name": {"type": "string"}}, required=["name"]),
            ),
        ]
    )


@server.request_handler("tools/call")
async def call_tool(ctx: RequestContext, request: JSONRPCRequest) -> CallToolResult:
    params = CallToolRequestParams.model_validate(request.params)
    await ctx.send_notification("notifications/message", {"level": "info", "message": "Loading tools"})
    if params.name == "greet":
        name = (params.arguments or {}).get("name", "world")
        return CallToolResult(content=[TextContent(text=f"Hello, {name}!")])
    return CallToolResult(content=[TextContent(text=f"Unknown tool: {params.name}")], is_error=True)


if __name__ == "__main__":
    anyio.run(run_stdio, server)
