"""The MCP method registry, as the `mcp.types.methods` namespace.

A mirror of `mcp_types.methods` (every name is the same object), so code that
depends on `mcp` can import from `mcp.types.methods` without importing the
`mcp_types` distribution directly. Depend on and import `mcp_types.methods`
instead when you use `mcp-types` without the SDK.
"""

# A wildcard mirror of the mcp_types.methods namespace is the whole point of this module.
# pyright: reportWildcardImportFromLibrary=false

from mcp_types.methods import *
from mcp_types.methods import __all__ as __all__
