"""MCP Resource Server (multiprotocol, path-only unified discovery variant).

Thin shim — see mcp_simple_auth_multiprotocol.server for the canonical implementation.
"""

from mcp_simple_auth_multiprotocol.server import VARIANT_PATH_ONLY, main_for_variant

main = main_for_variant(VARIANT_PATH_ONLY)
