from mcp_types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

from mcp.server import Server, ServerRequestContext

SEARCH_BOOKS = Tool(
    name="search_books",
    description="Search the catalog by title or author.",
    input_schema={
        "type": "object",
        "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
        "required": ["query", "limit"],
    },
)


async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[SEARCH_BOOKS])


async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    args = params.arguments or {}
    text = f"Found 3 books matching {args['query']!r} (showing up to {args['limit']})."
    return CallToolResult(content=[TextContent(type="text", text=text)])


server = Server("Bookshop", on_list_tools=list_tools, on_call_tool=call_tool)
