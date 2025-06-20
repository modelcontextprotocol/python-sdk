"""Tests for tool output in low-level server."""

import json
from typing import Any

import pytest

from mcp.server import Server
from mcp.types import CallToolRequest, CallToolRequestParams, CallToolResult, TextContent


@pytest.mark.anyio
async def test_lowlevel_server_traditional_tool_output():
    """Test that traditional content block output still works."""
    server = Server("test-server")

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "echo":
            message = arguments.get("message", "")
            return [TextContent(type="text", text=f"Echo: {message}")]
        else:
            raise ValueError(f"Unknown tool: {name}")

    # Call the handler directly
    request = CallToolRequest(
        method="tools/call", params=CallToolRequestParams(name="echo", arguments={"message": "Hello World"})
    )

    handler = server.request_handlers[CallToolRequest]
    result = await handler(request)

    # Verify traditional output
    assert isinstance(result.root, CallToolResult)
    assert result.root.content is not None
    assert len(result.root.content) == 1
    assert result.root.content[0].type == "text"
    assert result.root.content[0].text == "Echo: Hello World"
    assert result.root.structuredContent is None
    assert result.root.isError is False


@pytest.mark.anyio
async def test_lowlevel_server_structured_tool_output():
    """Test that structured dict output works correctly."""
    server = Server("test-server")

    expected_output = {
        "id": 42,
        "name": "John Doe",
        "email": "john@example.com",
    }

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> dict[str, Any]:
        if name == "get_user":
            return expected_output
        else:
            raise ValueError(f"Unknown tool: {name}")

    # Call the handler directly
    request = CallToolRequest(
        method="tools/call", params=CallToolRequestParams(name="get_user", arguments={"user_id": 42})
    )

    handler = server.request_handlers[CallToolRequest]
    result = await handler(request)

    assert isinstance(result.root, CallToolResult)
    assert result.root.content is not None
    assert len(result.root.content) == 1
    assert result.root.content[0].type == "text"

    parsed_content = json.loads(result.root.content[0].text)
    assert parsed_content == expected_output

    assert result.root.structuredContent is not None
    assert result.root.structuredContent == expected_output
    assert result.root.isError is False


@pytest.mark.anyio
async def test_lowlevel_server_structured_tool_output_complex():
    """Test structured output with nested and complex data."""
    server = Server("test-server")

    expected_output = {
        "id": "test-org",
        "name": "Acme Corp",
        "employees": [
            {"id": 1, "name": "Alice", "role": "CEO"},
            {"id": 2, "name": "Bob", "role": "CTO"},
        ],
        "metadata": {
            "founded": 2020,
            "public": True,
            "tags": ["tech", "startup"],
        },
    }

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> dict[str, Any]:
        if name == "get_organization":
            return expected_output
        else:
            raise ValueError(f"Unknown tool: {name}")

    # Call the handler directly
    request = CallToolRequest(
        method="tools/call", params=CallToolRequestParams(name="get_organization", arguments={"org_id": "test-org"})
    )

    handler = server.request_handlers[CallToolRequest]
    result = await handler(request)

    assert isinstance(result.root, CallToolResult)
    assert result.root.content is not None
    assert len(result.root.content) == 1
    assert result.root.content[0].type == "text"

    parsed_content = json.loads(result.root.content[0].text)
    assert parsed_content == expected_output

    assert result.root.structuredContent is not None
    assert result.root.structuredContent == expected_output
    assert result.root.isError is False


@pytest.mark.anyio
async def test_lowlevel_server_no_schema_validation():
    """Test that low-level server does NOT validate against schemas."""
    server = Server("test-server")

    # Server returns invalid output (string instead of integer)
    invalid_output = {
        "result": "not an integer",
        "extra_field": "should not be here",
        "another_extra": 123,
    }

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> dict[str, Any]:
        # Server doesn't validate - just returns the invalid data
        if name == "strict_tool":
            return invalid_output
        else:
            raise ValueError(f"Unknown tool: {name}")

    # Call the handler directly - no client involved
    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(
            name="strict_tool",
            arguments={"wrong_field": "value"},  # Invalid input
        ),
    )

    # The handler should be accessible via server.request_handlers
    handler = server.request_handlers[CallToolRequest]
    result = await handler(request)

    # Server returns the invalid output without validation
    assert isinstance(result.root, CallToolResult)
    assert result.root.content[0].type == "text"
    parsed_content = json.loads(result.root.content[0].text)
    assert parsed_content == invalid_output
    assert result.root.structuredContent == invalid_output
    assert result.root.isError is False


@pytest.mark.anyio
async def test_lowlevel_server_unstructured_multiple_content_blocks():
    """Test that servers can return multiple content blocks."""
    server = Server("test-server")

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "multi_response":
            return [
                TextContent(type="text", text="First response"),
                TextContent(type="text", text="Second response"),
                TextContent(type="text", text="Third response"),
            ]
        else:
            raise ValueError(f"Unknown tool: {name}")

    request = CallToolRequest(method="tools/call", params=CallToolRequestParams(name="multi_response", arguments={}))

    handler = server.request_handlers[CallToolRequest]
    result = await handler(request)

    assert isinstance(result.root, CallToolResult)
    assert result.root.content is not None
    assert len(result.root.content) == 3
    assert isinstance(result.root.content[0], TextContent)
    assert result.root.content[0].text == "First response"
    assert isinstance(result.root.content[1], TextContent)
    assert result.root.content[1].text == "Second response"
    assert isinstance(result.root.content[2], TextContent)
    assert result.root.content[2].text == "Third response"
    assert result.root.structuredContent is None
    assert result.root.isError is False


@pytest.mark.anyio
async def test_lowlevel_server_error_handling():
    """Test that server properly handles errors in tool execution."""
    server = Server("test-server")

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> dict[str, Any]:
        raise ValueError("Something went wrong")

    request = CallToolRequest(method="tools/call", params=CallToolRequestParams(name="failing_tool", arguments={}))

    handler = server.request_handlers[CallToolRequest]
    result = await handler(request)

    assert isinstance(result.root, CallToolResult)
    assert result.root.isError is True
    assert result.root.content is not None
    assert len(result.root.content) == 1
    assert result.root.content[0].type == "text"
    assert "Something went wrong" in result.root.content[0].text
    assert result.root.structuredContent is None
