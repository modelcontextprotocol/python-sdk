# pyright: reportGeneralTypeIssues=false
"""
MCP OAuth server authorization components.
"""

# Convenience re-exports so users can simply::
#
#     from mcp.server.auth import build_proxy_server
#
# instead of digging into the sub-package path.

from typing import TYPE_CHECKING

from mcp.server.auth.proxy import (
    configure_colored_logging,
    create_proxy_routes,
    fetch_upstream_metadata,
)

# For *build_proxy_server* we need a lazy import to avoid a circular reference
# during the initial package import sequence (FastMCP -> auth -> proxy ->
# FastMCP ...).  PEP 562 allows us to implement module-level `__getattr__` for
# this purpose.

def __getattr__(name: str):  # noqa: D401
    if name == "build_proxy_server":
        from mcp.server.auth.proxy.server import build_proxy_server as _bps  # noqa: WPS433

        globals()["build_proxy_server"] = _bps
        return _bps
    raise AttributeError(name)

# ---------------------------------------------------------------------------
# Public API specification
# ---------------------------------------------------------------------------

__all__: list[str] = [
    "configure_colored_logging",
    "create_proxy_routes",
    "fetch_upstream_metadata",
    "build_proxy_server",
]

if TYPE_CHECKING:  # pragma: no cover – make *build_proxy_server* visible to type checkers
    from mcp.server.auth.proxy.server import build_proxy_server  # noqa: F401
