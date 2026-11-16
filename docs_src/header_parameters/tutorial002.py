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


async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[CHECK_STOCK])


async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    args = params.arguments or {}
    text = f"{args['title']}: 3 copies in {args['region']}."
    return CallToolResult(content=[TextContent(type="text", text=text)])


server = Server("Bookshop", on_list_tools=list_tools, on_call_tool=call_tool)
app = server.streamable_http_app()
