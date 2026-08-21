"""Custom exceptions for MCPServer."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_types import ContentBlock


class MCPServerError(Exception):
    """Base error for MCPServer."""


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

    Raise this from a tool function to signal an execution error that
    the LLM should see (``CallToolResult(is_error=True)``).

    A plain ``ToolError("message")`` produces a text-only error result.
    To return arbitrary content (images, embedded resources, etc.)
    alongside the error flag, pass a ``content`` list::

        raise ToolError(
            "screenshot shows the failure",
            content=[
                TextContent(type="text", text="see attached"),
                ImageContent(type="image", data=b64, mime_type="image/png"),
            ],
        )
    """

    content: list[ContentBlock] | None

    def __init__(self, message: str = "", *, content: list[ContentBlock] | None = None) -> None:
        super().__init__(message)
        self.content = content


class InvalidSignature(Exception):
    """Invalid signature for use with MCPServer."""
