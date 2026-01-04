"""Test for issue #348: ToolError with custom content for isError responses.

Issue #348 reported that there was no way to set isError=True for arbitrary content
like Images. This was because ToolError only accepted a string message which was
converted to TextContent.

The fix adds an optional `content` parameter to ToolError that allows passing
arbitrary content blocks (TextContent, ImageContent, etc.) which will be returned
with isError=True.
"""

from typing import Any

import pytest

from mcp.server import Server
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.memory import (
    create_connected_server_and_client_session as client_session,
)
from mcp.types import ImageContent, TextContent, Tool

pytestmark = pytest.mark.anyio


def create_tool(name: str, description: str) -> Tool:
    """Create a test tool with the given name and description."""
    return Tool(name=name, description=description, inputSchema={"type": "object"})


async def test_tool_error_with_text_message():
    """Test that ToolError with just a message returns text content with isError=True."""
    server = Server("test")

    @server.list_tools()
    async def list_tools():
        return [create_tool("fail", "Always fails")]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]):
        raise ToolError("Something went wrong")

    async with client_session(server) as client:
        result = await client.call_tool("fail", {})

    assert result.isError is True
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    assert "Something went wrong" in result.content[0].text


async def test_tool_error_with_custom_text_content():
    """Test that ToolError with custom TextContent returns that content with isError=True."""
    server = Server("test")

    @server.list_tools()
    async def list_tools():
        return [create_tool("fail", "Fails with custom content")]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]):
        raise ToolError(
            "Error occurred",
            content=[
                TextContent(type="text", text="Custom error message 1"),
                TextContent(type="text", text="Custom error message 2"),
            ],
        )

    async with client_session(server) as client:
        result = await client.call_tool("fail", {})

    assert result.isError is True
    assert len(result.content) == 2
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "Custom error message 1"
    assert isinstance(result.content[1], TextContent)
    assert result.content[1].text == "Custom error message 2"


async def test_tool_error_with_image_content():
    """Test that ToolError with ImageContent returns image with isError=True."""
    server = Server("test")
    # Base64 encoded 1x1 red PNG
    red_pixel = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="

    @server.list_tools()
    async def list_tools():
        return [create_tool("fail", "Fails with image")]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]):
        raise ToolError(
            "Image processing failed",
            content=[
                ImageContent(type="image", data=red_pixel, mimeType="image/png"),
                TextContent(type="text", text="Error details"),
            ],
        )

    async with client_session(server) as client:
        result = await client.call_tool("fail", {})

    assert result.isError is True
    assert len(result.content) == 2
    assert isinstance(result.content[0], ImageContent)
    assert result.content[0].data == red_pixel
    assert result.content[0].mimeType == "image/png"
    assert isinstance(result.content[1], TextContent)
    assert result.content[1].text == "Error details"


async def test_tool_success_returns_is_error_false():
    """Test that successful tool call returns isError=False."""
    server = Server("test")

    @server.list_tools()
    async def list_tools():
        return [create_tool("succeed", "Always succeeds")]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]):
        return [TextContent(type="text", text="Success")]

    async with client_session(server) as client:
        result = await client.call_tool("succeed", {})

    assert result.isError is False
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "Success"


async def test_tool_error_with_empty_content_list():
    """Test that ToolError with empty content list returns empty content with isError=True."""
    server = Server("test")

    @server.list_tools()
    async def list_tools():
        return [create_tool("fail", "Fails with empty content")]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]):
        raise ToolError("Error message", content=[])

    async with client_session(server) as client:
        result = await client.call_tool("fail", {})

    assert result.isError is True
    assert len(result.content) == 0


# FastMCP tests - verify the feature works with the high-level API


async def test_fastmcp_tool_error_with_custom_content():
    """Test that ToolError with custom content works in FastMCP."""
    mcp = FastMCP("test")

    @mcp.tool()
    def fail_with_image() -> str:
        raise ToolError(
            "Processing failed",
            content=[
                ImageContent(
                    type="image",
                    data="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==",
                    mimeType="image/png",
                ),
                TextContent(type="text", text="Details about the failure"),
            ],
        )

    async with client_session(mcp) as client:
        result = await client.call_tool("fail_with_image", {})

    assert result.isError is True
    assert len(result.content) == 2
    assert isinstance(result.content[0], ImageContent)
    assert isinstance(result.content[1], TextContent)
    assert result.content[1].text == "Details about the failure"


async def test_fastmcp_tool_error_with_text_message():
    """Test that ToolError with just a message still works in FastMCP."""
    mcp = FastMCP("test")

    @mcp.tool()
    def fail_simple() -> str:
        raise ToolError("Simple error message")

    async with client_session(mcp) as client:
        result = await client.call_tool("fail_simple", {})

    assert result.isError is True
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    assert "Simple error message" in result.content[0].text


async def test_generic_exception_returns_error():
    """Test that a generic Exception (not ToolError) returns isError=True."""
    server = Server("test")

    @server.list_tools()
    async def list_tools():
        return [create_tool("fail", "Raises generic exception")]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]):
        raise ValueError("A generic error occurred")

    async with client_session(server) as client:
        result = await client.call_tool("fail", {})

    assert result.isError is True
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    assert "A generic error occurred" in result.content[0].text
