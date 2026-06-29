"""Example of implementing pagination with the low-level MCP server."""

import mcp_types as types

from mcp.server import Server, ServerRequestContext

ITEMS = [f"Item {i}" for i in range(1, 101)]


async def handle_list_resources(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListResourcesResult:
    """List resources with pagination support."""
    page_size = 10

    cursor = params.cursor if params is not None else None

    # The cursor is an opaque string; this server encodes the list offset in it
    start = 0 if cursor is None else int(cursor)
    end = start + page_size

    page_items = [
        types.Resource(uri=f"resource://items/{item}", name=item, description=f"Description for {item}")
        for item in ITEMS[start:end]
    ]

    next_cursor = str(end) if end < len(ITEMS) else None

    return types.ListResourcesResult(resources=page_items, next_cursor=next_cursor)


server = Server("paginated-server", on_list_resources=handle_list_resources)
