"""Basic tests for list_prompts, list_resources, and list_tools handlers without pagination."""

from typing import Any

import pytest

import mcp.types as types
from mcp.client.client import Client
from mcp.server import Server
from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext

pytestmark = pytest.mark.anyio


async def test_list_prompts_basic() -> None:
    """Test basic prompt listing without pagination."""
    test_prompts = [
        types.Prompt(name="prompt1", description="First prompt"),
        types.Prompt(name="prompt2", description="Second prompt"),
    ]

    async def handle_list_prompts(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=test_prompts)

    server = Server("test", on_list_prompts=handle_list_prompts)

    async with Client(server) as client:
        result = await client.list_prompts()
        assert result.prompts == test_prompts


async def test_list_resources_basic() -> None:
    """Test basic resource listing without pagination."""
    test_resources = [
        types.Resource(uri="file:///test1.txt", name="Test 1"),
        types.Resource(uri="file:///test2.txt", name="Test 2"),
    ]

    async def handle_list_resources(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=test_resources)

    server = Server("test", on_list_resources=handle_list_resources)

    async with Client(server) as client:
        result = await client.list_resources()
        assert result.resources == test_resources


async def test_list_tools_basic() -> None:
    """Test basic tool listing without pagination."""
    test_tools = [
        types.Tool(
            name="tool1",
            description="First tool",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                },
                "required": ["message"],
            },
        ),
        types.Tool(
            name="tool2",
            description="Second tool",
            inputSchema={
                "type": "object",
                "properties": {
                    "count": {"type": "number"},
                    "enabled": {"type": "boolean"},
                },
                "required": ["count"],
            },
        ),
    ]

    async def handle_list_tools(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=test_tools)

    server = Server("test", on_list_tools=handle_list_tools)

    async with Client(server) as client:
        result = await client.list_tools()
        assert result.tools == test_tools


async def test_list_prompts_empty() -> None:
    """Test listing with empty results."""

    async def handle_list_prompts(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=[])

    server = Server("test", on_list_prompts=handle_list_prompts)

    async with Client(server) as client:
        result = await client.list_prompts()
        assert result.prompts == []


async def test_list_resources_empty() -> None:
    """Test listing with empty results."""

    async def handle_list_resources(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=[])

    server = Server("test", on_list_resources=handle_list_resources)

    async with Client(server) as client:
        result = await client.list_resources()
        assert result.resources == []


async def test_list_tools_empty() -> None:
    """Test listing with empty results."""

    async def handle_list_tools(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[])

    server = Server("test", on_list_tools=handle_list_tools)

    async with Client(server) as client:
        result = await client.list_tools()
        assert result.tools == []
