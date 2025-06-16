"""Utility functions for working with metadata in MCP types."""

from mcp.types import Implementation, Prompt, Resource, ResourceTemplate, Tool


def get_display_name(obj: Tool | Resource | Prompt | ResourceTemplate | Implementation) -> str:
    """
    Get the display name for an MCP object with proper precedence.

    For tools: title > annotations.title > name
    For other objects: title > name

    Args:
        obj: An MCP object with name and optional title fields

    Returns:
        The display name to use for UI presentation
    """
    if isinstance(obj, Tool):
        # Tools have special precedence: title > annotations.title > name
        if hasattr(obj, "title") and obj.title is not None:
            return obj.title
        if obj.annotations and hasattr(obj.annotations, "title") and obj.annotations.title is not None:
            return obj.annotations.title
        return obj.name
    else:
        # All other objects: title > name
        if hasattr(obj, "title") and obj.title is not None:
            return obj.title
        return obj.name
