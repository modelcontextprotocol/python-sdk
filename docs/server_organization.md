# Organizing Larger FastMCP Servers

As your MCP server grows beyond the initial quickstart examples, you may find that organizing all tools, resources, and prompts in a single file becomes unwieldy. This guide presents a recommended pattern for structuring larger FastMCP servers and managing tool versions.

## When to Use This Pattern

Consider this organizational approach when:

- Your server exposes more than 5-10 tools
- You need to maintain multiple versions of tools
- Multiple developers are working on the codebase
- You want to separate concerns and improve code maintainability

For simple servers with just a few tools, the single-file quickstart pattern is perfectly fine.

## Recommended Project Layout

Here's the recommended structure for organizing a larger FastMCP server:

```text
my_fastmcp_server/
  server.py           # FastMCP wiring and server startup
  tools/
    __init__.py
    get_info.py       # get_info_v1, get_info_v2, ...
    other_tool.py     # other_tool_v1, ...
  resources/          # (optional) if you have many resources
    __init__.py
    ...
  prompts/            # (optional) if you have many prompts
    __init__.py
    ...
```

### Benefits of This Structure

**Per-tool modules** help with:

- **Code organization**: Each conceptual tool lives in its own file
- **Team collaboration**: Reduces merge conflicts when multiple developers work on different tools
- **Testing**: Makes unit testing individual tools easier
- **Documentation**: Tool implementations are self-contained and easier to document

**Multi-version functions in the same file** enable:

- **Easy comparison**: See all versions of a tool side-by-side
- **Reduced duplication**: Share helper functions between versions
- **Clear diffs**: Review changes between versions more easily
- **Maintenance**: Update shared logic across versions in one place

## Tool Versioning Pattern

FastMCP servers can expose multiple versions of a tool simultaneously using **name-based versioning**. This pattern works with the current SDK without requiring protocol-level versioning support.

### Version Naming Convention

Include the major version number in the tool name:

- `get_info_v1` - Version 1 of the tool
- `get_info_v2` - Version 2 of the tool
- `get_info_v3` - Version 3 of the tool

### When to Create a New Version

Create a new major version when making **breaking changes**:

- **Changed mandatory parameters**: Adding required parameters, removing parameters, or changing parameter types
- **Changed semantics**: Altering the tool's behavior in ways that would surprise existing clients
- **Changed output format**: Non-backward-compatible changes to the response structure
- **Changed side effects**: Modifications that would break existing client workflows

For **non-breaking changes** (bug fixes, performance improvements, additional optional parameters with defaults), keep the same version number.

## Complete Example

### Server Entrypoint (`server.py`)

<!-- snippet-source examples/snippets/servers/server_layout/server.py -->
```python
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
```

_Full example: [examples/snippets/servers/server_layout/server.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/server_layout/server.py)_
<!-- /snippet-source -->

### Tool Implementation (`tools/get_info.py`)

<!-- snippet-source examples/snippets/servers/server_layout/tools/get_info.py -->
```python
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
```

_Full example: [examples/snippets/servers/server_layout/tools/get_info.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/server_layout/tools/get_info.py)_
<!-- /snippet-source -->

## Running the Example

To run the complete example server:

```bash
# From the repository root
uv run examples/snippets/servers/server_layout/server.py
```

The server will start on `http://localhost:8000/mcp` and expose both `get_info_v1` and `get_info_v2` tools.

You can test it with the MCP Inspector:

```bash
npx -y @modelcontextprotocol/inspector
```

Then connect to `http://localhost:8000/mcp` in the inspector UI.

## Client Considerations

When connecting to servers that expose multiple tool versions:

### Using Tool Whitelists

Clients should use a **whitelist** to explicitly control which tools they interact with:

```python
# Client configuration (conceptual)
allowed_tools = [
    "get_info_v1",  # Use only v1 for now
    "other_tool_v2"
]

# Filter available tools based on whitelist
available_tools = await session.list_tools()
usable_tools = [
    tool for tool in available_tools.tools
    if tool.name in allowed_tools
]
```

### Version Selection Strategy

Clients can adopt different strategies:

- **Conservative**: Pin to a specific version (e.g., always use `v1`)
- **Latest stable**: Use the highest version known to be stable
- **Fallback chain**: Try `v2`, fall back to `v1` if unavailable
- **Per-operation**: Use different versions for different use cases

## Advanced Patterns

### Sharing Logic Between Versions

When multiple versions share common logic:

```python
def _fetch_data(topic: str) -> dict:
    """Internal helper shared by multiple versions."""
    # Common data fetching logic
    return {"raw_data": f"Data for {topic}"}


def get_info_v1(topic: str) -> str:
    """Version 1: simple output."""
    data = _fetch_data(topic)
    return f"Info: {data['raw_data']}"


def get_info_v2(topic: str) -> dict:
    """Version 2: structured output."""
    data = _fetch_data(topic)
    return {"topic": topic, "data": data["raw_data"]}
```

### Deprecating Old Versions

Use docstrings to communicate deprecation:

```python
def get_info_v1(topic: str) -> str:
    """Get basic information about a topic (v1).

    .. deprecated::
        Use get_info_v2 for richer structured output.
        This version will be removed in a future release.
    """
    # Implementation...
```

Server operators can remove old versions in new releases once clients have migrated.

## Future: Protocol-Level Versioning

This guide documents a pattern that works with the **current SDK** (main branch). The MCP protocol may introduce native tool versioning in the future, which would allow version metadata at the protocol level. When that becomes available, you'll be able to enhance this pattern with additional version fields while maintaining backward compatibility with name-based versioning.

## Summary

- **Single entrypoint** (`server.py`) for server wiring
- **Per-tool modules** (`tools/get_info.py`) for organization
- **Name-based versioning** (`get_info_v1`, `get_info_v2`) for managing breaking changes
- **Client whitelists** for explicit version control
- **Side-by-side versions** in the same module for easy comparison and maintenance

This pattern scales well as your server grows and helps maintain stability for clients as your tool APIs evolve.
