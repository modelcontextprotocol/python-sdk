import pytest

from mcp.server import Server
from mcp.types import (
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

    # Track what request was received
    received_request: ListPromptsRequest | None = None

    @server.list_prompts()
    async def handle_list_prompts(request: ListPromptsRequest) -> ListPromptsResult:
        nonlocal received_request
        received_request = request
        return ListPromptsResult(prompts=[], nextCursor="next")

    handler = server.request_handlers[ListPromptsRequest]

    # Test: No cursor provided -> handler receives request with None params
    request = ListPromptsRequest(method="prompts/list", params=None)
    result = await handler(request)
    assert received_request is not None
    assert received_request.params is None
    assert isinstance(result, ServerResult)

    # Test: Cursor provided -> handler receives request with cursor in params
    request_with_cursor = ListPromptsRequest(method="prompts/list", params=PaginatedRequestParams(cursor=test_cursor))
    result2 = await handler(request_with_cursor)
    assert received_request is not None
    assert received_request.params is not None
    assert received_request.params.cursor == test_cursor
    assert isinstance(result2, ServerResult)


@pytest.mark.anyio
async def test_list_resources_pagination() -> None:
    server = Server("test")
    test_cursor = "resource-cursor-456"

    # Track what request was received
    received_request: ListResourcesRequest | None = None

    @server.list_resources()
    async def handle_list_resources(request: ListResourcesRequest) -> ListResourcesResult:
        nonlocal received_request
        received_request = request
        return ListResourcesResult(resources=[], nextCursor="next")

    handler = server.request_handlers[ListResourcesRequest]

    # Test: No cursor provided -> handler receives request with None params
    request = ListResourcesRequest(method="resources/list", params=None)
    result = await handler(request)
    assert received_request is not None
    assert received_request.params is None
    assert isinstance(result, ServerResult)

    # Test: Cursor provided -> handler receives request with cursor in params
    request_with_cursor = ListResourcesRequest(
        method="resources/list", params=PaginatedRequestParams(cursor=test_cursor)
    )
    result2 = await handler(request_with_cursor)
    assert received_request is not None
    assert received_request.params is not None
    assert received_request.params.cursor == test_cursor
    assert isinstance(result2, ServerResult)


@pytest.mark.anyio
async def test_list_tools_pagination() -> None:
    server = Server("test")
    test_cursor = "tools-cursor-789"

    # Track what request was received
    received_request: ListToolsRequest | None = None

    @server.list_tools()
    async def handle_list_tools(request: ListToolsRequest) -> ListToolsResult:
        nonlocal received_request
        received_request = request
        return ListToolsResult(tools=[], nextCursor="next")

    handler = server.request_handlers[ListToolsRequest]

    # Test: No cursor provided -> handler receives request with None params
    request = ListToolsRequest(method="tools/list", params=None)
    result = await handler(request)
    assert received_request is not None
    assert received_request.params is None
    assert isinstance(result, ServerResult)

    # Test: Cursor provided -> handler receives request with cursor in params
    request_with_cursor = ListToolsRequest(method="tools/list", params=PaginatedRequestParams(cursor=test_cursor))
    result2 = await handler(request_with_cursor)
    assert received_request is not None
    assert received_request.params is not None
    assert received_request.params.cursor == test_cursor
    assert isinstance(result2, ServerResult)
