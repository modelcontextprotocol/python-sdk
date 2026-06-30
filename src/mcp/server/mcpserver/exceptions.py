"""Custom exceptions for MCPServer."""

from typing import Any


class MCPServerError(Exception):
    """Base error for MCPServer."""


class ValidationError(MCPServerError):
    """Error in validating parameters or return values."""


class ResourceError(MCPServerError):
    """Error in resource operations."""


class ResourceNotFoundError(ResourceError):
    """Resource does not exist.

    Raise this from a resource template handler to signal that the requested instance does not exist;
    clients receive `-32602` (invalid params) per
    [SEP-2164](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2164).
    """


class ToolError(MCPServerError):
    """Error in tool operations.

    Raise this from a tool function to return a ``CallToolResult`` with
    ``is_error=True``. By default the error message becomes the result's text
    content. Pass ``content`` to attach arbitrary result content - for example an
    image or embedded resource - to the error result instead of the message text.
    """

    def __init__(self, message: str = "", *, content: list[Any] | None = None) -> None:
        # `content` carries `mcp.types.ContentBlock` items. It is typed as
        # `list[Any]` rather than `list[ContentBlock]` because this module is
        # imported during `mcp` package initialization, before `mcp.types` is
        # importable - referencing that type here would create a circular import.
        # `_handle_call_tool` places the items straight into `CallToolResult.content`.
        super().__init__(message)
        self.content = content


class InvalidSignature(Exception):
    """Invalid signature for use with MCPServer."""
