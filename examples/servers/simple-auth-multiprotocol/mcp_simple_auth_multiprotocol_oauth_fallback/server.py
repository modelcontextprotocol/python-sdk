"""MCP Resource Server (multiprotocol, OAuth-fallback discovery variant).

Thin shim — see mcp_simple_auth_multiprotocol.server for the canonical implementation.
"""

from mcp_simple_auth_multiprotocol.server import VARIANT_OAUTH_FALLBACK, main_for_variant

main = main_for_variant(VARIANT_OAUTH_FALLBACK)
