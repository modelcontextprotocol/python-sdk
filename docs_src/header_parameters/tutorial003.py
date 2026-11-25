from typing import Any

from mcp.server import Server, ServerRequestContext
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

CHECK_STOCK = Tool(
    name="check_stock",
    description="Count the copies of a book in one region's warehouses.",
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "region": {"type": "string", "x-mcp-header": "Region"},
        },
        "required": ["title", "region"],
    },
)

TOOLS = {CHECK_STOCK.name: CHECK_STOCK}


async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=list(TOOLS.values()))


async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    args = params.arguments or {}
    text = f"{args['title']}: 3 copies in {args['region']}."
    return CallToolResult(content=[TextContent(type="text", text=text)])


def tool_input_schema(name: str) -> dict[str, Any] | None:
    tool = TOOLS.get(name)
    return tool.input_schema if tool else None


server = Server(
    "Bookshop",
    on_list_tools=list_tools,
    on_call_tool=call_tool,
    get_tool_input_schema=tool_input_schema,
)
app = server.streamable_http_app()
