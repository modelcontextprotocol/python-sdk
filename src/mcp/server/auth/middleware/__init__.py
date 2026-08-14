"""Middleware for MCP authorization."""

from typing import TYPE_CHECKING

from mcp.shared._lazy import lazy_module_attrs as _lazy_module_attrs

# `mcp.server.auth.middleware.<module>` resolves by attribute access even
# before that submodule was imported explicitly, like the other packages.
# Runtime only, so a type checker still flags a typo.
if not TYPE_CHECKING:
    __getattr__, __dir__ = _lazy_module_attrs(__name__, globals())
