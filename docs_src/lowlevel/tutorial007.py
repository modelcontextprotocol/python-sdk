from mcp.server import Server, ServerRequestContext
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams, TextContent, Tool

FIND_BOOK = Tool(
    name="find_book",
    description="Find one book by ISBN, or by title and author.",
    input_schema={
        "type": "object",
        "properties": {
            "isbn": {"type": "string", "pattern": "^[0-9]{13}$"},
            "title": {"type": "string"},
            "author": {"type": "string"},
        },
        "oneOf": [{"required": ["isbn"]}, {"required": ["title", "author"]}],
        "additionalProperties": False,
    },
)


async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=[FIND_BOOK])


async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    args = params.arguments or {}
    found = f"ISBN {args['isbn']}" if "isbn" in args else f"{args['title']!r} by {args['author']}"
    return CallToolResult(content=[TextContent(type="text", text=f"Found {found} on shelf C-3.")])


server = Server("Bookshop", on_list_tools=list_tools, on_call_tool=call_tool)
