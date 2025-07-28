"""MCP Snippets.

This package contains simple examples of MCP server features.
Each server demonstrates a single feature and can be run as a standalone server.

To run a server, use the command:
    uv run server basic_tool sse
"""

import importlib
import sys
from typing import Literal, cast


def run_server():
    """Run a server by name with optional transport.

    Usage: server <server-name> [transport]
    Example: server basic_tool sse
    """
    if len(sys.argv) < 2:
        print("Usage: server <server-name> [transport]")
        print("Available servers: basic_tool, basic_resource, basic_prompt, tool_progress,")
        print("                   sampling, elicitation, completion, notifications,")
        print("                   fastmcp_quickstart, structured_output, images")
        print("Available transports: stdio (default), sse, streamable-http")
        sys.exit(1)

    server_name = sys.argv[1]
    transport = sys.argv[2] if len(sys.argv) > 2 else "stdio"

    try:
        module = importlib.import_module(f".{server_name}", package=__name__)
        module.mcp.run(cast(Literal["stdio", "sse", "streamable-http"], transport))
    except ImportError:
        print(f"Error: Server '{server_name}' not found")
        sys.exit(1)
