"""Common URI utilities for FastMCP."""

from collections.abc import Sequence
from typing import Protocol, TypeVar, runtime_checkable

from pydantic import AnyUrl

from mcp.types import PROMPT_SCHEME, TOOL_SCHEME

T = TypeVar("T", bound="HasUri")


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


@runtime_checkable
class HasUri(Protocol):
    """Protocol for objects that have a URI attribute."""

    uri: AnyUrl


def filter_by_uri_paths(items: Sequence[T], uri_paths: Sequence[AnyUrl]) -> list[T]:
    """Filter items by multiple URI path prefixes.

    Args:
        items: List of items that have a 'uri' attribute
        uri_paths: List of URI path prefixes to filter by.

    Returns:
        Filtered list of items matching any of the provided prefixes
    """

    # Filter items where the URI matches any of the prefixes
    filtered: list[T] = []
    for item in items:
        uri = str(item.uri)
        for prefix in uri_paths:
            prefix_str = str(prefix)
            if uri.startswith(prefix_str):
                # If prefix ends with a separator, we already have a proper boundary
                if prefix_str.endswith(("/", "?", "#")):
                    filtered.append(item)
                    break
                # Otherwise check if it's an exact match or if the next character is a separator
                elif len(uri) == len(prefix_str) or uri[len(prefix_str)] in ("/", "?", "#"):
                    filtered.append(item)
                    break

    return filtered
