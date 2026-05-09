"""Tests for ToolError with custom content (issue #348).

Verifies that ToolError can carry arbitrary content blocks (images, embedded
resources, etc.) and that they are returned to the client with isError=True.
"""

import pytest

from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ImageContent, TextContent

pytestmark = pytest.mark.anyio


def _make_image_content() -> ImageContent:
    return ImageContent(type="image", data="aWNvbg==", mime_type="image/png")


class TestToolErrorContent:
    async def test_tool_error_text_only_unchanged(self):
        """Raising ToolError with just a message still works as before."""
        mcp = MCPServer()

        @mcp.tool()
        def failing_tool() -> str:
            """A tool that fails."""
            raise ToolError("something broke")

        async with Client(mcp) as client:
            result = await client.call_tool("failing_tool", {})
            assert result.is_error is True
            assert len(result.content) == 1
            assert isinstance(result.content[0], TextContent)
            assert "something broke" in result.content[0].text

    async def test_tool_error_with_image_content(self):
        """ToolError with custom image content returns that content with isError."""
        mcp = MCPServer()

        @mcp.tool()
        def image_error_tool() -> str:
            """A tool that fails with image content."""
            raise ToolError(
                "Image processing failed",
                content=[
                    _make_image_content(),
                    TextContent(type="text", text="Additional error details"),
                ],
            )

        async with Client(mcp) as client:
            result = await client.call_tool("image_error_tool", {})
            assert result.is_error is True
            assert len(result.content) == 2
            assert isinstance(result.content[0], ImageContent)
            assert result.content[0].mime_type == "image/png"
            assert isinstance(result.content[1], TextContent)
            assert result.content[1].text == "Additional error details"

    async def test_tool_error_with_single_text_content(self):
        """ToolError with explicit TextContent list uses that instead of str(e)."""
        mcp = MCPServer()

        @mcp.tool()
        def explicit_text_error() -> str:
            """A tool that fails with explicit text content."""
            raise ToolError(
                "ignored message",
                content=[TextContent(type="text", text="Custom error message")],
            )

        async with Client(mcp) as client:
            result = await client.call_tool("explicit_text_error", {})
            assert result.is_error is True
            assert len(result.content) == 1
            assert isinstance(result.content[0], TextContent)
            assert result.content[0].text == "Custom error message"

    async def test_tool_error_content_none_falls_back_to_message(self):
        """ToolError with content=None uses the message string as before."""
        mcp = MCPServer()

        @mcp.tool()
        def none_content_error() -> str:
            """A tool that fails with content=None."""
            raise ToolError("fallback message", content=None)

        async with Client(mcp) as client:
            result = await client.call_tool("none_content_error", {})
            assert result.is_error is True
            assert len(result.content) == 1
            assert isinstance(result.content[0], TextContent)
            assert "fallback message" in result.content[0].text

    async def test_generic_exception_still_returns_is_error(self):
        """Non-ToolError exceptions still produce isError=True (no regression)."""
        mcp = MCPServer()

        @mcp.tool()
        def generic_error_tool() -> str:
            """A tool that raises a generic exception."""
            raise RuntimeError("unexpected failure")

        async with Client(mcp) as client:
            result = await client.call_tool("generic_error_tool", {})
            assert result.is_error is True
            assert len(result.content) == 1
            assert isinstance(result.content[0], TextContent)
            assert "unexpected failure" in result.content[0].text
