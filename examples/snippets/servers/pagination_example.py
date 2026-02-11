"""Example of implementing pagination with MCP server constructor kwargs."""

from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server

# Sample data to paginate
ITEMS = [f"Item {i}" for i in range(1, 101)]  # 100 items


async def handle_list_resources(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListResourcesResult:
    """List resources with pagination support."""
    page_size = 10

    # Extract cursor from params
    cursor = params.cursor if params is not None else None

    # Parse cursor to get offset
    start = 0 if cursor is None else int(cursor)
    end = start + page_size

    # Get page of resources
    page_items = [
        types.Resource(uri=f"resource://items/{item}", name=item, description=f"Description for {item}")
        for item in ITEMS[start:end]
    ]

    # Determine next cursor
    next_cursor = str(end) if end < len(ITEMS) else None

    return types.ListResourcesResult(resources=page_items, next_cursor=next_cursor)


# Initialize the server
server = Server("paginated-server", on_list_resources=handle_list_resources)
