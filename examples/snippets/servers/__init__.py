"""MCP Snippets.

This package contains simple examples of MCP server features.
Each server demonstrates a single feature and can be run as a standalone server.
"""

import sys
from typing import Literal


def run_server(module_name: str, transport: Literal["stdio", "sse", "streamable-http"] | None = None) -> None:
    """Run a snippet server with the specified transport.

    Args:
        module_name: Name of the snippet module to run
        transport: Transport to use (stdio, sse, streamable-http).
                  If None, uses first command line arg or defaults to stdio.
    """
    # Import the specific module based on name
    if module_name == "basic_tool":
        from . import basic_tool

        mcp = basic_tool.mcp
    elif module_name == "basic_resource":
        from . import basic_resource

        mcp = basic_resource.mcp
    elif module_name == "basic_prompt":
        from . import basic_prompt

        mcp = basic_prompt.mcp
    elif module_name == "tool_progress":
        from . import tool_progress

        mcp = tool_progress.mcp
    elif module_name == "sampling":
        from . import sampling

        mcp = sampling.mcp
    elif module_name == "elicitation":
        from . import elicitation

        mcp = elicitation.mcp
    elif module_name == "completion":
        from . import completion

        mcp = completion.mcp
    elif module_name == "notifications":
        from . import notifications

        mcp = notifications.mcp
    else:
        raise ValueError(f"Unknown module: {module_name}")

    # Determine transport
    if transport is None:
        transport_arg = sys.argv[1] if len(sys.argv) > 1 else "stdio"
        # Validate and cast transport
        if transport_arg not in ["stdio", "sse", "streamable-http"]:
            raise ValueError(f"Invalid transport: {transport_arg}. Must be one of: stdio, sse, streamable-http")
        transport = transport_arg  # type: ignore

    # Run the server
    print(f"Starting {module_name} server with {transport} transport...")
    mcp.run(transport=transport)  # type: ignore


# Entry points for each snippet
def run_basic_tool():
    """Run the basic tool example server."""
    run_server("basic_tool")


def run_basic_resource():
    """Run the basic resource example server."""
    run_server("basic_resource")


def run_basic_prompt():
    """Run the basic prompt example server."""
    run_server("basic_prompt")


def run_tool_progress():
    """Run the tool progress example server."""
    run_server("tool_progress")


def run_sampling():
    """Run the sampling example server."""
    run_server("sampling")


def run_elicitation():
    """Run the elicitation example server."""
    run_server("elicitation")


def run_completion():
    """Run the completion example server."""
    run_server("completion")


def run_notifications():
    """Run the notifications example server."""
    run_server("notifications")
