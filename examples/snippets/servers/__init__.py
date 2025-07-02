"""MCP Snippets.

This package contains simple examples of MCP server features.
Each server demonstrates a single feature and can be run as a standalone server.
"""

import importlib
import sys
from typing import Literal

# Available snippet modules
SNIPPET_MODULES = [
    "basic_tool",
    "basic_resource",
    "basic_prompt",
    "tool_progress",
    "sampling",
    "elicitation",
    "completion",
    "notifications",
]


def run_server(module_name: str, transport: Literal["stdio", "sse", "streamable-http"] | None = None) -> None:
    """Run a snippet server with the specified transport.

    Args:
        module_name: Name of the snippet module to run
        transport: Transport to use (stdio, sse, streamable-http).
                  If None, uses first command line arg or defaults to stdio.
    """
    # Validate module name
    if module_name not in SNIPPET_MODULES:
        raise ValueError(f"Unknown module: {module_name}. Available modules: {', '.join(SNIPPET_MODULES)}")

    # Import the module dynamically
    module = importlib.import_module(f".{module_name}", package=__name__)
    mcp = module.mcp

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


# Create entry point functions dynamically
def _create_run_function(module_name: str):
    """Create a run function for a specific module."""

    def run_function():
        f"""Run the {module_name.replace('_', ' ')} example server."""
        run_server(module_name)

    return run_function


# Generate entry points for each snippet
for module in SNIPPET_MODULES:
    func_name = f"run_{module}"
    globals()[func_name] = _create_run_function(module)