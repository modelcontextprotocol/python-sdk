"""The JSON-RPC 2.0 message and error types, as the `mcp.types.jsonrpc` namespace.

A mirror of `mcp_types.jsonrpc` (every name is the same object), so code that
depends on `mcp` can import from `mcp.types.jsonrpc` without importing the
`mcp_types` distribution directly. Depend on and import `mcp_types.jsonrpc`
instead when you use `mcp-types` without the SDK.
"""

# A wildcard mirror of the mcp_types.jsonrpc namespace is the whole point of this module.
# pyright: reportWildcardImportFromLibrary=false

from mcp_types.jsonrpc import *
from mcp_types.jsonrpc import __all__ as __all__
