"""
Example FastMCP server demonstrating recommended layout for larger servers.

This server shows how to:
- Organize tools into separate modules
- Implement versioned tools using name-based versioning
- Structure a maintainable FastMCP server

Run from the repository root:
    uv run examples/snippets/servers/server_layout/server.py
"""

from mcp.server.fastmcp import FastMCP

# Import tool implementations from the tools package
from servers.server_layout.tools import get_info

# Create the FastMCP server instance
mcp = FastMCP("ServerLayoutDemo", json_response=True)


# Register version 1 of the get_info tool
# The function name determines the tool name exposed to clients
@mcp.tool()
def get_info_v1(topic: str) -> str:
    """Get basic information about a topic (v1).

    Version 1 provides simple string output with basic information.

    Args:
        topic: The topic to get information about

    Returns:
        A simple string with basic information
    """
    return get_info.get_info_v1(topic)


# Register version 2 of the get_info tool
# Breaking changes from v1: different return type and new parameter
@mcp.tool()
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
    return get_info.get_info_v2(topic, include_metadata)


# Run the server
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
