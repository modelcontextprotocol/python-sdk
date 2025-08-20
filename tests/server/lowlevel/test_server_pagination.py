import pytest

from mcp.server import Server
from mcp.types import (
    Cursor,
    ListPromptsRequest,
    ListPromptsResult,
    ListResourcesRequest,
    ListResourcesResult,
    ListToolsRequest,
    ListToolsResult,
    PaginatedRequestParams,
    ServerResult,
)


@pytest.mark.anyio
async def test_list_prompts_pagination() -> None:
    server = Server("test")
    test_cursor = "test-cursor-123"
    
    # Track what cursor was received
    received_cursor: Cursor | None = None
    
    @server.list_prompts_paginated()
    async def handle_list_prompts(cursor: Cursor | None) -> ListPromptsResult:
        nonlocal received_cursor
        received_cursor = cursor
        return ListPromptsResult(prompts=[], nextCursor="next")
    
    handler = server.request_handlers[ListPromptsRequest]
    
    # Test: No cursor provided -> handler receives None
    request = ListPromptsRequest(method="prompts/list", params=None)
    result = await handler(request)
    assert received_cursor is None
    assert isinstance(result, ServerResult)
    
    # Test: Cursor provided -> handler receives exact cursor value
    request_with_cursor = ListPromptsRequest(
        method="prompts/list",
        params=PaginatedRequestParams(cursor=test_cursor)
    )
    result2 = await handler(request_with_cursor)
    assert received_cursor == test_cursor
    assert isinstance(result2, ServerResult)


@pytest.mark.anyio
async def test_list_resources_pagination() -> None:
    server = Server("test")
    test_cursor = "resource-cursor-456"
    
    # Track what cursor was received
    received_cursor: Cursor | None = None
    
    @server.list_resources_paginated()
    async def handle_list_resources(cursor: Cursor | None) -> ListResourcesResult:
        nonlocal received_cursor
        received_cursor = cursor
        return ListResourcesResult(resources=[], nextCursor="next")
    
    handler = server.request_handlers[ListResourcesRequest]
    
    # Test: No cursor provided -> handler receives None
    request = ListResourcesRequest(method="resources/list", params=None)
    result = await handler(request)
    assert received_cursor is None
    assert isinstance(result, ServerResult)
    
    # Test: Cursor provided -> handler receives exact cursor value
    request_with_cursor = ListResourcesRequest(
        method="resources/list",
        params=PaginatedRequestParams(cursor=test_cursor)
    )
    result2 = await handler(request_with_cursor)
    assert received_cursor == test_cursor
    assert isinstance(result2, ServerResult)


@pytest.mark.anyio
async def test_list_tools_pagination() -> None:
    server = Server("test")
    test_cursor = "tools-cursor-789"
    
    # Track what cursor was received
    received_cursor: Cursor | None = None
    
    @server.list_tools_paginated()
    async def handle_list_tools(cursor: Cursor | None) -> ListToolsResult:
        nonlocal received_cursor
        received_cursor = cursor
        return ListToolsResult(tools=[], nextCursor="next")
    
    handler = server.request_handlers[ListToolsRequest]
    
    # Test: No cursor provided -> handler receives None
    request = ListToolsRequest(method="tools/list", params=None)
    result = await handler(request)
    assert received_cursor is None
    assert isinstance(result, ServerResult)
    
    # Test: Cursor provided -> handler receives exact cursor value
    request_with_cursor = ListToolsRequest(
        method="tools/list",
        params=PaginatedRequestParams(cursor=test_cursor)
    )
    result2 = await handler(request_with_cursor)
    assert received_cursor == test_cursor
    assert isinstance(result2, ServerResult)
