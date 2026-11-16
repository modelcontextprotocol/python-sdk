from typing import Any

from mcp import MCPError
from mcp.server import Server, ServerRequestContext
from mcp.server.context import CallNext, HandlerResult, ServerMiddleware
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

# MCP defines no "busy" error, so this server picks its own code.
SERVER_BUSY = 1


async def on_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(
        tools=[
            Tool(
                name="search_books",
                description="Search the catalog by title or author.",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            )
        ]
    )


async def on_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    query = (params.arguments or {})["query"]
    return CallToolResult(content=[TextContent(type="text", text=f"Found 3 books matching {query!r}.")])


def max_concurrent_tool_calls(limit: int) -> ServerMiddleware[Any]:
    running = 0

    async def middleware(ctx: ServerRequestContext, call_next: CallNext) -> HandlerResult:
        nonlocal running
        if ctx.method != "tools/call":
            return await call_next(ctx)
        if running >= limit:
            raise MCPError(code=SERVER_BUSY, message=f"Server busy: tool call limit reached ({limit} in progress).")
        running += 1
        try:
            return await call_next(ctx)
        finally:
            running -= 1

    return middleware


server = Server("Bookshop", on_list_tools=on_list_tools, on_call_tool=on_call_tool)
server.middleware.append(max_concurrent_tool_calls(4))
