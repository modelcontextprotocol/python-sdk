"""Basic tests for on_list_prompts, on_list_resources, and on_list_tools handlers without pagination."""

import pytest

from mcp.server import Server
from mcp.server.context import ServerRequestContext
from mcp.types import (
    ListPromptsResult,
    ListResourcesResult,
    ListToolsResult,
    Prompt,
    Resource,
    Tool,
)

pytestmark = pytest.mark.anyio


async def test_list_prompts_basic() -> None:
    """Test basic prompt listing without pagination."""
    test_prompts = [
        Prompt(name="prompt1", description="First prompt"),
        Prompt(name="prompt2", description="Second prompt"),
    ]

    async def handle_list_prompts(ctx: ServerRequestContext, params: None) -> ListPromptsResult:
        return ListPromptsResult(prompts=test_prompts)

    server = Server("test", on_list_prompts=handle_list_prompts)

    assert "prompts/list" in server._request_handlers
    result = await server._request_handlers["prompts/list"](None, None)  # type: ignore[arg-type]

    assert isinstance(result, ListPromptsResult)
    assert result.prompts == test_prompts


async def test_list_resources_basic() -> None:
    """Test basic resource listing without pagination."""
    test_resources = [
        Resource(uri="file:///test1.txt", name="Test 1"),
        Resource(uri="file:///test2.txt", name="Test 2"),
    ]

    async def handle_list_resources(ctx: ServerRequestContext, params: None) -> ListResourcesResult:
        return ListResourcesResult(resources=test_resources)

    server = Server("test", on_list_resources=handle_list_resources)

    assert "resources/list" in server._request_handlers
    result = await server._request_handlers["resources/list"](None, None)  # type: ignore[arg-type]

    assert isinstance(result, ListResourcesResult)
    assert result.resources == test_resources


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

    async def handle_list_tools(ctx: ServerRequestContext, params: None) -> ListToolsResult:
        return ListToolsResult(tools=test_tools)

    server = Server("test", on_list_tools=handle_list_tools)

    assert "tools/list" in server._request_handlers
    result = await server._request_handlers["tools/list"](None, None)  # type: ignore[arg-type]

    assert isinstance(result, ListToolsResult)
    assert result.tools == test_tools


async def test_list_prompts_empty() -> None:
    """Test listing with empty results."""

    async def handle_list_prompts(ctx: ServerRequestContext, params: None) -> ListPromptsResult:
        return ListPromptsResult(prompts=[])

    server = Server("test", on_list_prompts=handle_list_prompts)
    result = await server._request_handlers["prompts/list"](None, None)  # type: ignore[arg-type]

    assert isinstance(result, ListPromptsResult)
    assert result.prompts == []


async def test_list_resources_empty() -> None:
    """Test listing with empty results."""

    async def handle_list_resources(ctx: ServerRequestContext, params: None) -> ListResourcesResult:
        return ListResourcesResult(resources=[])

    server = Server("test", on_list_resources=handle_list_resources)
    result = await server._request_handlers["resources/list"](None, None)  # type: ignore[arg-type]

    assert isinstance(result, ListResourcesResult)
    assert result.resources == []


async def test_list_tools_empty() -> None:
    """Test listing with empty results."""

    async def handle_list_tools(ctx: ServerRequestContext, params: None) -> ListToolsResult:
        return ListToolsResult(tools=[])

    server = Server("test", on_list_tools=handle_list_tools)
    result = await server._request_handlers["tools/list"](None, None)  # type: ignore[arg-type]

    assert isinstance(result, ListToolsResult)
    assert result.tools == []
