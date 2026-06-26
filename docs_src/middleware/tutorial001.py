import logging
import time

from mcp_types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

from mcp.server import Server, ServerRequestContext
from mcp.server.context import CallNext, HandlerResult

logger = logging.getLogger(__name__)


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


async def log_timing(ctx: ServerRequestContext, call_next: CallNext) -> HandlerResult:
    start = time.perf_counter()
    try:
        return await call_next(ctx)
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info("%s took %.1f ms", ctx.method, elapsed_ms)


server = Server("Bookshop", on_list_tools=on_list_tools, on_call_tool=on_call_tool)
server.middleware.append(log_timing)
