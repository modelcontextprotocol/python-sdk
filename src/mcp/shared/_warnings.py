"""Warning categories emitted by the `mcp` package."""

from __future__ import annotations

__all__ = ["MCPDeprecationWarning"]


class MCPDeprecationWarning(UserWarning):
    """Deprecation warning emitted by the `mcp` package.

    Subclasses `UserWarning` (not `DeprecationWarning`) so it is visible by default —
    `DeprecationWarning` is silenced at the Python level for non-`__main__` callers.

    Defined in its own module so that pytest's `filterwarnings` parser can resolve the
    category symbol without importing any side-effecting module — e.g.
    `mcp.shared._httpx` emits a `MCPDeprecationWarning` at import time when only `httpx`
    is installed, and resolving the symbol through that module would fire the warning
    before pytest finishes registering the filter.
    """
