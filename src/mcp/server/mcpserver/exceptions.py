"""Custom exceptions for MCPServer."""
from __future__ import annotations


class MCPServerError(Exception):
    """Base error for MCPServer."""


class ValidationError(MCPServerError):
    """Error in validating parameters or return values."""


class ResourceError(MCPServerError):
    """Error in resource operations."""


class ToolError(MCPServerError):
    """Error in tool operations.

    Can be raised from tool functions to return a tool result with
    is_error=True and arbitrary content (e.g., images, structured data).

    Args:
        message: Error message (used as text content if no content provided).
        content: Optional list of ContentBlock items to return as tool result content.
        is_error: Whether to set is_error on the CallToolResult (default True).
    """

    def __init__(
        self,
        message: str,
        *,
        content: list | None = None,
        is_error: bool = True,
    ) -> None:
        super().__init__(message)
        self.content = content
        self.is_error = is_error


class InvalidSignature(Exception):
    """Invalid signature for use with MCPServer."""
