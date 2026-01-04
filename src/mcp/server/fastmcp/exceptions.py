"""Custom exceptions for FastMCP."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.types import ContentBlock


class FastMCPError(Exception):
    """Base error for FastMCP."""


class ValidationError(FastMCPError):
    """Error in validating parameters or return values."""


class ResourceError(FastMCPError):
    """Error in resource operations."""


class ToolError(FastMCPError):
    """Error in tool operations.

    Can be raised with custom content to return non-text error responses.

    Args:
        message: Error message (used if content is not provided)
        content: Optional list of content blocks to return as the error response.
            If provided, these will be used instead of the message for the error content.

    Examples:
        # Simple text error (existing behavior)
        raise ToolError("Something went wrong")

        # Error with custom content (e.g., image)
        raise ToolError(
            "Image processing failed",
            content=[ImageContent(type="image", data="...", mimeType="image/png")]
        )
    """

    def __init__(
        self,
        message: str = "",
        *,
        content: list[ContentBlock] | None = None,
    ) -> None:
        super().__init__(message)
        self.content = content


class InvalidSignature(Exception):
    """Invalid signature for use with FastMCP."""
