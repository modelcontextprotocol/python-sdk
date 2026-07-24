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

ADD_BOOK = Tool(
    name="add_book",
    description="Add a book to the catalog.",
    input_schema={
        "type": "object",
        "properties": {"title": {"type": "string"}, "author": {"type": "string"}, "year": {"type": "integer"}},
        "required": ["title", "author", "year"],
    },
)


async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[SEARCH_BOOKS, ADD_BOOK])


async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    args = params.arguments or {}
    if params.name == "search_books":
        text = f"Found 3 books matching {args['query']!r} (showing up to {args['limit']})."
    elif params.name == "add_book":
        text = f"Added {args['title']!r} by {args['author']} ({args['year']})."
    else:
        raise ValueError(f"Unknown tool: {params.name}")
    return CallToolResult(content=[TextContent(type="text", text=text)])


server = Server("Bookshop", on_list_tools=list_tools, on_call_tool=call_tool)
