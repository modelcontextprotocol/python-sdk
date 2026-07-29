"""Platform-specific utilities for MCP."""

from mcp.shared._lazy_submodules import submodule_getattr as _submodule_getattr

# `mcp.os.posix` / `mcp.os.win32` resolve by attribute access even before they
# were imported.
__getattr__ = _submodule_getattr(__name__)
