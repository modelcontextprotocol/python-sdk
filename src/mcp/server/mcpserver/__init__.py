"""MCPServer - A more ergonomic interface for MCP servers."""

from mcp_types import Icon

from mcp.server.extension import Extension, MethodBinding, ResourceBinding, ToolBinding

from .context import Context
from .resources import DEFAULT_RESOURCE_SECURITY, ResourceSecurity
from .server import MCPServer, require_client_extension
from .utilities.types import Audio, Image

__all__ = [
    "MCPServer",
    "Context",
    "Image",
    "Audio",
    "Icon",
    "Extension",
    "ToolBinding",
    "ResourceBinding",
    "MethodBinding",
    "require_client_extension",
    "ResourceSecurity",
    "DEFAULT_RESOURCE_SECURITY",
]
