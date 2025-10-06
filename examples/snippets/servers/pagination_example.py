"""
Example of implementing pagination with MCP server decorators.
"""

from pydantic import AnyUrl

import mcp.types as types
from mcp.server.lowlevel import Server

# Initialize the server
server = Server("paginated-server")

# Sample data to paginate
ITEMS = [f"Item {i}" for i in range(1, 101)]  # 100 items


@server.list_resources()
async def list_resources_paginated(request: types.ListResourcesRequest) -> types.ListResourcesResult:
    """List resources with pagination support."""
    page_size = 10

    # Extract cursor from request params
    cursor = request.params.cursor if request.params is not None else None

    # Parse cursor to get offset
    start = 0 if cursor is None else int(cursor)
    end = start + page_size

    # Get page of resources
    page_items = [
        types.Resource(uri=AnyUrl(f"resource://items/{item}"), name=item, description=f"Description for {item}")
        for item in ITEMS[start:end]
    ]

    # Determine next cursor
    next_cursor = str(end) if end < len(ITEMS) else None

    return types.ListResourcesResult(resources=page_items, nextCursor=next_cursor)
