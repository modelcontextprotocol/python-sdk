"""The protocol-version registry, as the `mcp.types.version` namespace.

A mirror of `mcp_types.version` (every name is the same object), so code that
depends on `mcp` can write `from mcp.types.version import LATEST_MODERN_VERSION`
without importing the `mcp_types` distribution directly. Depend on and import
`mcp_types.version` instead when you use `mcp-types` without the SDK.
"""

# A wildcard mirror of the mcp_types.version namespace is the whole point of this module.
# pyright: reportWildcardImportFromLibrary=false

from mcp_types.version import *
from mcp_types.version import __all__ as __all__
