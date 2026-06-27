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
    output_schema={
        "type": "object",
        "properties": {"matches": {"type": "integer"}, "query": {"type": "string"}},
        "required": ["matches", "query"],
    },
)


async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[SEARCH_BOOKS])


async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    args = params.arguments or {}
    data = {"matches": 3, "query": args["query"]}
    return CallToolResult(
        content=[TextContent(type="text", text=f"Found 3 books matching {args['query']!r}.")],
        structured_content=data,
    )


server = Server("Bookshop", on_list_tools=list_tools, on_call_tool=call_tool)
