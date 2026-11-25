"""The MCP protocol wire types, as the `mcp.types` namespace.

This module mirrors the standalone `mcp_types` package exactly (every name is the
same object), so SDK users can keep the familiar v1 spelling:

    import mcp.types as types

    types.TextContent(type="text", text="hi")

The `mcp.types.jsonrpc`, `mcp.types.methods`, and `mcp.types.version`
submodules mirror `mcp_types.jsonrpc`, `mcp_types.methods`, and
`mcp_types.version` the same way, so every supported `mcp_types` import has
an `mcp.types` spelling.

Depend on and import `mcp_types` directly instead when you only need to
(de)serialize MCP traffic and don't want the SDK's transport stack: its only
runtime dependencies are `pydantic` and `typing-extensions`.
"""

# A wildcard mirror of the mcp_types namespace is the whole point of this module.
# pyright: reportWildcardImportFromLibrary=false

from mcp_types import *
from mcp_types import __all__ as __all__

# Bind the mirror submodules on the package, so `mcp.types.version.X` is as
# reachable by attribute access as `mcp_types.version.X` (whose `__init__`
# binds `.version` by importing from it), not only via `from ... import`.
from . import jsonrpc as jsonrpc
from . import methods as methods
from . import version as version
