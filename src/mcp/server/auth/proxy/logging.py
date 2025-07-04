"""Proxy logging utilities now delegate to the global FastMCP logger.

Historically the transparent OAuth proxy shipped its own coloured / emoji
logging setup.  To avoid duplication we now defer to
`fastmcp.utilities.logging.configure_logging` and simply provide a thin
compatibility shim so existing code that imports
`mcp.server.auth.proxy.logging.configure_colored_logging` continues to work.
"""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp.utilities.logging import configure_logging

__all__ = ["configure_colored_logging"]


def configure_colored_logging(  # noqa: D401
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "DEBUG"
) -> None:
    """Compatibility wrapper mapping to the shared FastMCP logging helper."""

    # Delegate directly to the shared FastMCP utility.
    configure_logging(level=level) 