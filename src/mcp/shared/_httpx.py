"""Compatibility shim: prefer `httpx2`, fall back to `httpx` with a deprecation warning.

Mirrors the pattern from
[Kludex/starlette@508023b](https://github.com/Kludex/starlette/commit/508023b488b649d97c091eb60da1d8ef3636ee06)
and [pydantic/pydantic-ai#5664](https://github.com/pydantic/pydantic-ai/pull/5664).

`httpx2` is not yet on PyPI, so every install today exercises the fallback path. The warning
is emitted lazily on first use (not at module import) to avoid breaking pytest's filter
parser during collection. The MCP v2 cut will drop the fallback and require `httpx2`.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

__all__ = ["MCPDeprecationWarning", "emit_httpx_deprecation_warning", "httpx"]


class MCPDeprecationWarning(UserWarning):
    """Deprecation warning emitted by the `mcp` package.

    Subclasses `UserWarning` (not `DeprecationWarning`) so it is visible by default —
    `DeprecationWarning` is silenced at the Python level for non-`__main__` callers.
    """


if TYPE_CHECKING:
    import httpx as httpx

    _HTTPX_IS_DEPRECATED = False
else:
    try:
        import httpx2 as httpx

        _HTTPX_IS_DEPRECATED = False
    except ImportError:
        import httpx

        _HTTPX_IS_DEPRECATED = True


_warning_emitted = False


def emit_httpx_deprecation_warning() -> None:
    """Emit the `httpx` → `httpx2` deprecation warning at most once per process."""
    global _warning_emitted
    if _HTTPX_IS_DEPRECATED and not _warning_emitted:
        _warning_emitted = True
        warnings.warn(
            "Using `httpx` with `mcp` is deprecated; install `httpx2` instead.",
            MCPDeprecationWarning,
            stacklevel=3,
        )
