"""Platform-specific utilities for MCP."""

from typing import TYPE_CHECKING

from mcp.shared._lazy import lazy_module_attrs as _lazy_module_attrs

# `mcp.os.posix` / `mcp.os.win32` resolve by attribute access even before they
# were imported. Runtime only, so a type checker still flags a typo.
if not TYPE_CHECKING:
    __getattr__, __dir__ = _lazy_module_attrs(__name__, globals())
