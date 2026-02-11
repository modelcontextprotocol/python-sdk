"""Tests for pagination support in on_list_prompts, on_list_resources, and on_list_tools handlers."""

import pytest

from mcp.server import Server
from mcp.server.context import ServerRequestContext
from mcp.types import (
    ListPromptsResult,
    ListResourcesResult,
    ListToolsResult,
    PaginatedRequestParams,
)

pytestmark = pytest.mark.anyio


async def test_list_prompts_pagination() -> None:
    received_params: PaginatedRequestParams | None = "NOT_SET"  # type: ignore[assignment]

    async def handle_list_prompts(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListPromptsResult:
        nonlocal received_params
        received_params = params
        return ListPromptsResult(prompts=[], next_cursor="next")

    server = Server("test", on_list_prompts=handle_list_prompts)

    # Test: No cursor provided -> handler receives None params
    result = await server._request_handlers["prompts/list"](None, None)  # type: ignore[arg-type]
    assert received_params is None
    assert isinstance(result, ListPromptsResult)

    # Test: Cursor provided -> handler receives params with cursor
    test_cursor = "test-cursor-123"
    params = PaginatedRequestParams(cursor=test_cursor)
    result2 = await server._request_handlers["prompts/list"](None, params)  # type: ignore[arg-type]
    assert received_params is not None
    assert received_params.cursor == test_cursor
    assert isinstance(result2, ListPromptsResult)


async def test_list_resources_pagination() -> None:
    received_params: PaginatedRequestParams | None = "NOT_SET"  # type: ignore[assignment]

    async def handle_list_resources(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListResourcesResult:
        nonlocal received_params
        received_params = params
        return ListResourcesResult(resources=[], next_cursor="next")

    server = Server("test", on_list_resources=handle_list_resources)

    # Test: No cursor provided
    result = await server._request_handlers["resources/list"](None, None)  # type: ignore[arg-type]
    assert received_params is None
    assert isinstance(result, ListResourcesResult)

    # Test: Cursor provided
    test_cursor = "resource-cursor-456"
    params = PaginatedRequestParams(cursor=test_cursor)
    result2 = await server._request_handlers["resources/list"](None, params)  # type: ignore[arg-type]
    assert received_params is not None
    assert received_params.cursor == test_cursor
    assert isinstance(result2, ListResourcesResult)


async def test_list_tools_pagination() -> None:
    received_params: PaginatedRequestParams | None = "NOT_SET"  # type: ignore[assignment]

    async def handle_list_tools(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        nonlocal received_params
        received_params = params
        return ListToolsResult(tools=[], next_cursor="next")

    server = Server("test", on_list_tools=handle_list_tools)

    # Test: No cursor provided
    result = await server._request_handlers["tools/list"](None, None)  # type: ignore[arg-type]
    assert received_params is None
    assert isinstance(result, ListToolsResult)

    # Test: Cursor provided
    test_cursor = "tools-cursor-789"
    params = PaginatedRequestParams(cursor=test_cursor)
    result2 = await server._request_handlers["tools/list"](None, params)  # type: ignore[arg-type]
    assert received_params is not None
    assert received_params.cursor == test_cursor
    assert isinstance(result2, ListToolsResult)
