"""Client-side utilities for displaying human-readable names in a spec-compliant way."""

from mcp_types import Implementation, Prompt, Resource, ResourceTemplate, Tool


def get_display_name(obj: Tool | Resource | Prompt | ResourceTemplate | Implementation) -> str:
    """Get the display name for an MCP object for UI presentation.

    Precedence for tools: `title` > `annotations.title` > `name`. For all other
    objects: `title` > `name`.
    """
    if isinstance(obj, Tool):
        if hasattr(obj, "title") and obj.title is not None:
            return obj.title
        if obj.annotations and hasattr(obj.annotations, "title") and obj.annotations.title is not None:
            return obj.annotations.title
        return obj.name
    else:
        if hasattr(obj, "title") and obj.title is not None:
            return obj.title
        return obj.name
