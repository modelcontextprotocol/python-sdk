"""Common URI utilities for FastMCP."""

from collections.abc import Callable
from typing import TypeVar

from pydantic import AnyUrl

from mcp.types import PROMPT_SCHEME, TOOL_SCHEME

T = TypeVar("T")


def normalize_to_uri(name_or_uri: str, scheme: str) -> str:
    """Convert name to URI if needed.

    Args:
        name_or_uri: Either a name or a full URI
        scheme: The URI scheme to use (e.g., TOOL_SCHEME or PROMPT_SCHEME)

    Returns:
        A properly formatted URI
    """
    if name_or_uri.startswith(scheme):
        return name_or_uri
    return f"{scheme}/{name_or_uri}"


def normalize_to_tool_uri(name_or_uri: str) -> str:
    """Convert name to tool URI if needed."""
    return normalize_to_uri(name_or_uri, TOOL_SCHEME)


def normalize_to_prompt_uri(name_or_uri: str) -> str:
    """Convert name to prompt URI if needed."""
    return normalize_to_uri(name_or_uri, PROMPT_SCHEME)


def filter_by_prefix(items: list[T], prefix: str | None, uri_getter: Callable[[T], AnyUrl | str]) -> list[T]:
    """Filter items by URI prefix.

    Args:
        items: List of items to filter
        prefix: Optional prefix to filter by. If None, returns all items.
        uri_getter: Function to extract URI from an item

    Returns:
        Filtered list of items
    """
    if not prefix:
        return items

    # Filter items where the URI starts with the prefix
    filtered: list[T] = []
    for item in items:
        uri = str(uri_getter(item))
        if uri.startswith(prefix):
            # If prefix ends with a separator, we already have a proper boundary
            if prefix.endswith(("/", "?", "#")):
                filtered.append(item)
            # Otherwise check if it's an exact match or if the next character is a separator
            elif len(uri) == len(prefix) or uri[len(prefix)] in ("/", "?", "#"):
                filtered.append(item)

    return filtered
