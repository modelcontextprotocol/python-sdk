import pytest

from mcp import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    ListPromptsResult,
    ListResourcesResult,
    ListToolsResult,
    PaginatedRequestParams,
)


@pytest.mark.anyio
async def test_list_prompts_pagination() -> None:
    test_cursor = "test-cursor-123"
    received_params: PaginatedRequestParams | None = None

    async def handle_list_prompts(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListPromptsResult:
        nonlocal received_params
        received_params = params
        return ListPromptsResult(prompts=[], next_cursor="next")

    server = Server("test", on_list_prompts=handle_list_prompts)
    async with Client(server) as client:
        # No cursor provided
        await client.list_prompts()
        assert received_params is not None
        assert received_params.cursor is None

        # Cursor provided
        await client.list_prompts(cursor=test_cursor)
        assert received_params is not None
        assert received_params.cursor == test_cursor


@pytest.mark.anyio
async def test_list_resources_pagination() -> None:
    test_cursor = "resource-cursor-456"
    received_params: PaginatedRequestParams | None = None

    async def handle_list_resources(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListResourcesResult:
        nonlocal received_params
        received_params = params
        return ListResourcesResult(resources=[], next_cursor="next")

    server = Server("test", on_list_resources=handle_list_resources)
    async with Client(server) as client:
        # No cursor provided
        await client.list_resources()
        assert received_params is not None
        assert received_params.cursor is None

        # Cursor provided
        await client.list_resources(cursor=test_cursor)
        assert received_params is not None
        assert received_params.cursor == test_cursor


@pytest.mark.anyio
async def test_list_tools_pagination() -> None:
    test_cursor = "tools-cursor-789"
    received_params: PaginatedRequestParams | None = None

    async def handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        nonlocal received_params
        received_params = params
        return ListToolsResult(tools=[], next_cursor="next")

    server = Server("test", on_list_tools=handle_list_tools)
    async with Client(server) as client:
        # No cursor provided
        await client.list_tools()
        assert received_params is not None
        assert received_params.cursor is None

        # Cursor provided
        await client.list_tools(cursor=test_cursor)
        assert received_params is not None
        assert received_params.cursor == test_cursor
