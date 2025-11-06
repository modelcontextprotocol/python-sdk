"""Custom exceptions for FastMCP."""

from typing import Any

from mcp.types import INTERNAL_ERROR, ErrorData


class FastMCPError(Exception):
    """Base error for FastMCP."""


class ValidationError(FastMCPError):
    """Error in validating parameters or return values."""


class ResourceError(FastMCPError):
    """Error in resource operations.

    Defaults to INTERNAL_ERROR (-32603), but can be set to RESOURCE_NOT_FOUND (-32002)
    for resource not found errors per MCP spec.
    """

    error: ErrorData

    def __init__(self, message: str, code: int = INTERNAL_ERROR, data: Any | None = None):
        """Initialize ResourceError with error code and message.

        Args:
            message: Error message
            code: Error code (defaults to INTERNAL_ERROR -32603, use RESOURCE_NOT_FOUND -32002 for not found)
        """
        super().__init__(message)
        self.error = ErrorData(code=code, message=message, data=data)


class ToolError(FastMCPError):
    """Error in tool operations."""


class InvalidSignature(Exception):
    """Invalid signature for use with FastMCP."""
