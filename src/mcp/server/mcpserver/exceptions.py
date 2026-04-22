"""Custom exceptions for MCPServer."""


class MCPServerError(Exception):
    """Base error for MCPServer."""


class ValidationError(MCPServerError):
    """Error in validating parameters or return values."""


class ResourceError(MCPServerError):
    """Error in resource operations."""


class ResourceNotFoundError(ResourceError):
    """Resource does not exist.

    Raise this from a resource template handler to signal that the requested
    instance does not exist; clients receive ``-32602`` (invalid params) per
    SEP-2164.
    """


class ToolError(MCPServerError):
    """Error in tool operations."""


class InvalidSignature(Exception):
    """Invalid signature for use with MCPServer."""
