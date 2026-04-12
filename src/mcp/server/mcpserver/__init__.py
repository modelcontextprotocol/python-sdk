"""MCPServer - A more ergonomic interface for MCP servers."""

from mcp.types import Icon

from .context import Context
from .server import MCPServer
from .utilities.roots import assert_within_roots, get_roots, within_roots_check
from .utilities.types import Audio, Image

__all__ = [
    "MCPServer",
    "Context",
    "Image",
    "Audio",
    "Icon",
    "assert_within_roots",
    "get_roots",
    "within_roots_check",
]
