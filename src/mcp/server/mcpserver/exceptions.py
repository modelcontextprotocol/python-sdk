"""Custom exceptions for MCPServer."""


class MCPServerError(Exception):
    """Base error for MCPServer."""


class ValidationError(MCPServerError):
    """Error in validating parameters or return values."""


class ResourceError(MCPServerError):
    """Error in resource operations."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class ToolError(MCPServerError):
    """Error in tool operations."""


class InvalidSignature(Exception):
    """Invalid signature for use with MCPServer."""
