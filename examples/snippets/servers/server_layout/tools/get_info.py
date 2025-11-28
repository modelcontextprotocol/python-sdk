"""
Example tool module showing versioned tool implementations.

This module demonstrates the recommended pattern for managing
multiple versions of a tool in a single file.
"""


def get_info_v1(topic: str) -> str:
    """Get basic information about a topic (v1).

    Version 1 provides simple string output with basic information.

    Args:
        topic: The topic to get information about

    Returns:
        A simple string with basic information
    """
    return f"Information about {topic}: This is version 1 with basic details."


def get_info_v2(topic: str, include_metadata: bool = False) -> dict[str, str | dict[str, str]]:
    """Get information about a topic with optional metadata (v2).

    Version 2 introduces breaking changes:
    - Returns structured dict instead of string (breaking change)
    - Adds include_metadata parameter for richer output

    Args:
        topic: The topic to get information about
        include_metadata: Whether to include additional metadata

    Returns:
        A dictionary with structured information
    """
    result: dict[str, str | dict[str, str]] = {
        "topic": topic,
        "description": f"This is version 2 with enhanced details about {topic}.",
        "version": "2",
    }

    if include_metadata:
        result["metadata"] = {
            "source": "server_layout_example",
            "confidence": "high",
        }

    return result
