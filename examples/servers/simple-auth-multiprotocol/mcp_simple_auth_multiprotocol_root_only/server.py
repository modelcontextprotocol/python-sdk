"""MCP Resource Server (multiprotocol, root-only unified discovery variant).

Thin shim — see mcp_simple_auth_multiprotocol.server for the canonical implementation.
"""

from mcp_simple_auth_multiprotocol.server import VARIANT_ROOT_ONLY, main_for_variant

main = main_for_variant(VARIANT_ROOT_ONLY)
