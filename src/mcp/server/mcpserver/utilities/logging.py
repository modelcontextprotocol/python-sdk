"""Logging utilities for MCPServer."""

import logging
from typing import Literal


def get_logger(name: str) -> logging.Logger:
    """Get a logger nested under MCP namespace.

    Args:
        name: The name of the logger.

    Returns:
        A configured logger instance.
    """
    return logging.getLogger(name)


def configure_logging(
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "WARNING",
) -> None:
    """Configure logging for MCP.

    Configures the ``mcp`` logger (not the root logger) so that library code
    does not accidentally install handlers on the root namespace.  This keeps
    third-party libraries (httpx, urllib3, …) from routing their INFO-level
    output through a RichHandler that writes to stderr, which can fill the
    kernel's stderr SNDBUF and deadlock a stdio-transport MCP server under
    back-pressure from the host process.

    The function is idempotent: if the ``mcp`` logger already has handlers the
    call is a no-op, allowing application code to configure logging before
    instantiating :class:`~mcp.server.mcpserver.server.MCPServer`.

    Args:
        level: The log level to use (default ``"WARNING"``).
    """
    mcp_logger = logging.getLogger("mcp")

    # Idempotent: skip if already configured.
    if mcp_logger.handlers:
        return

    try:
        from rich.console import Console
        from rich.logging import RichHandler

        mcp_logger.addHandler(RichHandler(console=Console(stderr=True), rich_tracebacks=True))
    except ImportError:  # pragma: no cover
        mcp_logger.addHandler(logging.StreamHandler())

    mcp_logger.setLevel(level)
    # Do not propagate to the root logger; we own our own handler.
    mcp_logger.propagate = False
