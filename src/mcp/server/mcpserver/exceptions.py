"""Custom exceptions for MCPServer."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.types import ContentBlock


class MCPServerError(Exception):
    """Base error for MCPServer."""


class ValidationError(MCPServerError):
    """Error in validating parameters or return values."""


class ResourceError(MCPServerError):
    """Error in resource operations."""


class ToolError(MCPServerError):
    """Error in tool operations.

    Can optionally carry rich content blocks (images, embedded resources, etc.)
    that will be returned to the agent with ``isError=True``.

    Examples:
        Simple text error (existing behavior, unchanged)::

            raise ToolError("Something went wrong")

        Error with custom content::

            raise ToolError(
                "Image processing failed",
                content=[
                    ImageContent(type="image", data="...", mimeType="image/png"),
                    TextContent(type="text", text="Additional error details"),
                ],
            )
    """

    content: list[ContentBlock] | None

    def __init__(self, message: str, content: list[ContentBlock] | None = None) -> None:
        super().__init__(message)
        self.content = content


class InvalidSignature(Exception):
    """Invalid signature for use with MCPServer."""
