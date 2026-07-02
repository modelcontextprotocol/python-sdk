from mcp_types import (
    INVALID_PARAMS,
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

from mcp import MCPError
from mcp.server import Server, ServerRequestContext

SEARCH_BOOKS = Tool(
    name="search_books",
    description="Search the catalog by title or author.",
    input_schema={  # (1)!
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
)


async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:  # (2)!
    return ListToolsResult(tools=[SEARCH_BOOKS])  # (3)!


async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:  # (4)!
    if params.name != "search_books":
        raise MCPError(INVALID_PARAMS, f"Unknown tool: {params.name}")  # (5)!
    args = params.arguments or {}  # (6)!
    text = f"Found 3 books matching {args['query']!r}."
    return CallToolResult(content=[TextContent(type="text", text=text)])  # (7)!


server = Server("Bookshop", on_list_tools=list_tools, on_call_tool=call_tool)  # (8)!
