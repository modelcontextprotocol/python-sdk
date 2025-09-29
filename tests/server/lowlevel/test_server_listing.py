"""Basic tests for list_prompts, list_resources, and list_tools decorators without pagination."""

import warnings

import pytest
from pydantic import AnyUrl

from mcp.server import Server
from mcp.types import (
    ListPromptsRequest,
    ListPromptsResult,
    ListResourcesRequest,
    ListResourcesResult,
    ListToolsRequest,
    ListToolsResult,
    Prompt,
    Resource,
    ServerResult,
    Tool,
)


@pytest.mark.anyio
async def test_list_prompts_basic() -> None:
    """Test basic prompt listing without pagination."""
    server = Server("test")

    test_prompts = [
        Prompt(name="prompt1", description="First prompt"),
        Prompt(name="prompt2", description="Second prompt"),
    ]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)

        @server.list_prompts()
        async def handle_list_prompts() -> list[Prompt]:
            return test_prompts

    handler = server.request_handlers[ListPromptsRequest]
    request = ListPromptsRequest(method="prompts/list", params=None)
    result = await handler(request)

    assert isinstance(result, ServerResult)
    assert isinstance(result.root, ListPromptsResult)
    assert result.root.prompts == test_prompts


@pytest.mark.anyio
async def test_list_resources_basic() -> None:
    """Test basic resource listing without pagination."""
    server = Server("test")

    test_resources = [
        Resource(uri=AnyUrl("file:///test1.txt"), name="Test 1"),
        Resource(uri=AnyUrl("file:///test2.txt"), name="Test 2"),
    ]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)

        @server.list_resources()
        async def handle_list_resources() -> list[Resource]:
            return test_resources

    handler = server.request_handlers[ListResourcesRequest]
    request = ListResourcesRequest(method="resources/list", params=None)
    result = await handler(request)

    assert isinstance(result, ServerResult)
    assert isinstance(result.root, ListResourcesResult)
    assert result.root.resources == test_resources


@pytest.mark.anyio
async def test_list_tools_basic() -> None:
    """Test basic tool listing without pagination."""
    server = Server("test")

    test_tools = [
        Tool(
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
        Tool(
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

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)

        @server.list_tools()
        async def handle_list_tools() -> list[Tool]:
            return test_tools

    handler = server.request_handlers[ListToolsRequest]
    request = ListToolsRequest(method="tools/list", params=None)
    result = await handler(request)

    assert isinstance(result, ServerResult)
    assert isinstance(result.root, ListToolsResult)
    assert result.root.tools == test_tools


@pytest.mark.anyio
async def test_list_prompts_empty() -> None:
    """Test listing with empty results."""
    server = Server("test")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)

        @server.list_prompts()
        async def handle_list_prompts() -> list[Prompt]:
            return []

    handler = server.request_handlers[ListPromptsRequest]
    request = ListPromptsRequest(method="prompts/list", params=None)
    result = await handler(request)

    assert isinstance(result, ServerResult)
    assert isinstance(result.root, ListPromptsResult)
    assert result.root.prompts == []


@pytest.mark.anyio
async def test_list_resources_empty() -> None:
    """Test listing with empty results."""
    server = Server("test")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)

        @server.list_resources()
        async def handle_list_resources() -> list[Resource]:
            return []

    handler = server.request_handlers[ListResourcesRequest]
    request = ListResourcesRequest(method="resources/list", params=None)
    result = await handler(request)

    assert isinstance(result, ServerResult)
    assert isinstance(result.root, ListResourcesResult)
    assert result.root.resources == []


@pytest.mark.anyio
async def test_list_tools_empty() -> None:
    """Test listing with empty results."""
    server = Server("test")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)

        @server.list_tools()
        async def handle_list_tools() -> list[Tool]:
            return []

    handler = server.request_handlers[ListToolsRequest]
    request = ListToolsRequest(method="tools/list", params=None)
    result = await handler(request)

    assert isinstance(result, ServerResult)
    assert isinstance(result.root, ListToolsResult)
    assert result.root.tools == []
