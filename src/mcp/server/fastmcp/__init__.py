"""Deprecated import path: `FastMCP` was renamed to `MCPServer` in v2.

This module keeps `from mcp.server.fastmcp import FastMCP` working so v1 code
runs, but importing it emits an `MCPDeprecationWarning`. It is not a
behaviour-preserving alias: v2 changed defaults and semantics beyond the name
(the default server name, transport parameters moving off the constructor,
sync handlers running on a worker thread). Read the migration guide before
relying on it:

    https://py.sdk.modelcontextprotocol.io/v2/migration/

Only this package init is shimmed. Submodules such as
`mcp.server.fastmcp.server` or `mcp.server.fastmcp.prompts.base` no longer
exist; their contents live under `mcp.server.mcpserver`. This module is removed
in v3.
"""

import warnings

from mcp.server.mcpserver import Audio, Context, Icon, Image
from mcp.server.mcpserver import MCPServer as FastMCP
from mcp.shared.exceptions import MCPDeprecationWarning

warnings.warn(
    "mcp.server.fastmcp is deprecated: FastMCP was renamed to MCPServer "
    "(from mcp.server.mcpserver import MCPServer). This is not just a rename; "
    "defaults and behaviour changed in v2, see the migration guide: "
    "https://py.sdk.modelcontextprotocol.io/v2/migration/. "
    "This import path will be removed in v3.",
    MCPDeprecationWarning,
    stacklevel=2,
)

__all__ = ["FastMCP", "Context", "Image", "Audio", "Icon"]
