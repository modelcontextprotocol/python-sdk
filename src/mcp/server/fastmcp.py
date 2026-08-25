"""Removed in mcp 2: `FastMCP` is now `mcp.server.mcpserver.MCPServer`.

This module has no API. Importing it, or anything below it, raises
`ModuleNotFoundError` with a message that points at the migration guide. It
exists only because the bare "No module named 'mcp.server.fastmcp'" gave v1
code no hint that the installed SDK is a different major version.
"""

_MESSAGE = (
    "No module named 'mcp.server.fastmcp'. This is mcp 2.x, where FastMCP was renamed to MCPServer "
    "(from mcp.server.mcpserver import MCPServer) and other APIs changed; see the migration guide at "
    "https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver "
    "or pin 'mcp<2' to keep running v1 code."
)

raise ModuleNotFoundError(_MESSAGE, name=__name__)
