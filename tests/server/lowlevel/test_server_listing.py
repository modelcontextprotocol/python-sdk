"""Basic tests for list_prompts, list_resources, and list_tools handlers without pagination."""

import pytest

from mcp import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    ListPromptsResult,
    ListResourcesResult,
    ListToolsResult,
    PaginatedRequestParams,
    Prompt,
    Resource,
    Tool,
)


@pytest.mark.anyio
async def test_list_prompts_basic() -> None:
    """Test basic prompt listing without pagination."""
    test_prompts = [
        Prompt(name="prompt1", description="First prompt"),
        Prompt(name="prompt2", description="Second prompt"),
    ]

    async def handle_list_prompts(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListPromptsResult:
        return ListPromptsResult(prompts=test_prompts)

    server = Server("test", on_list_prompts=handle_list_prompts)
    async with Client(server) as client:
        result = await client.list_prompts()
        assert result.prompts == test_prompts


@pytest.mark.anyio
async def test_list_resources_basic() -> None:
    """Test basic resource listing without pagination."""
    test_resources = [
        Resource(uri="file:///test1.txt", name="Test 1"),
        Resource(uri="file:///test2.txt", name="Test 2"),
    ]

    async def handle_list_resources(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListResourcesResult:
        return ListResourcesResult(resources=test_resources)

    server = Server("test", on_list_resources=handle_list_resources)
    async with Client(server) as client:
        result = await client.list_resources()
        assert result.resources == test_resources


@pytest.mark.anyio
async def test_list_tools_basic() -> None:
    """Test basic tool listing without pagination."""
    test_tools = [
        Tool(
            name="tool1",
            description="First tool",
            input_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                },
                "required": ["message"],
            },
        ),
        Tool(
            name="tool2",
            description="Second tool",
            input_schema={
                "type": "object",
                "properties": {
                    "count": {"type": "number"},
                    "enabled": {"type": "boolean"},
                },
                "required": ["count"],
            },
        ),
    ]

    async def handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=test_tools)

    server = Server("test", on_list_tools=handle_list_tools)
    async with Client(server) as client:
        result = await client.list_tools()
        assert result.tools == test_tools


@pytest.mark.anyio
async def test_list_prompts_empty() -> None:
    """Test listing with empty results."""

    async def handle_list_prompts(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListPromptsResult:
        return ListPromptsResult(prompts=[])

    server = Server("test", on_list_prompts=handle_list_prompts)
    async with Client(server) as client:
        result = await client.list_prompts()
        assert result.prompts == []


@pytest.mark.anyio
async def test_list_resources_empty() -> None:
    """Test listing with empty results."""

    async def handle_list_resources(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListResourcesResult:
        return ListResourcesResult(resources=[])

    server = Server("test", on_list_resources=handle_list_resources)
    async with Client(server) as client:
        result = await client.list_resources()
        assert result.resources == []


@pytest.mark.anyio
async def test_list_tools_empty() -> None:
    """Test listing with empty results."""

    async def handle_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[])

    server = Server("test", on_list_tools=handle_list_tools)
    async with Client(server) as client:
        result = await client.list_tools()
        assert result.tools == []
