"""Compatibility shim: prefer `httpx2`, fall back to `httpx` with a deprecation warning.

Mirrors the pattern from
[Kludex/starlette@508023b](https://github.com/Kludex/starlette/commit/508023b488b649d97c091eb60da1d8ef3636ee06)
and [pydantic/pydantic-ai#5664](https://github.com/pydantic/pydantic-ai/pull/5664).

`mcp` declares `httpx` (not `httpx2`) as a dependency, so unless the user installs `httpx2`
explicitly the fallback path is exercised. The MCP v2 cut will drop the fallback and bump the
dependency to `httpx2`.

The warning is emitted at module-import time and fires at most once per process via Python's
module cache. `MCPDeprecationWarning` lives in `mcp.shared._warnings` so pytest's
`filterwarnings` parser can resolve the category symbol without importing this shim.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

from mcp.shared._warnings import MCPDeprecationWarning

__all__ = ["MCPDeprecationWarning", "httpx"]


if TYPE_CHECKING:
    import httpx as httpx
else:
    try:
        import httpx2 as httpx
    except ImportError:
        import httpx

        warnings.warn(
            "Using `httpx` with `mcp` is deprecated; install `httpx2` instead.",
            MCPDeprecationWarning,
            stacklevel=2,
        )
