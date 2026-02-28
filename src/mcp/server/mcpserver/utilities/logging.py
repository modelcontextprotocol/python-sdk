"""Logging utilities for MCPServer."""

import logging
from typing import Literal

# Namespace logger for all MCP SDK logging.
# Per Python logging best practices, library code should only configure
# its own namespace logger, never the root logger.
_MCP_LOGGER_NAME = "mcp"


def get_logger(name: str) -> logging.Logger:
    """Get a logger nested under MCP namespace.

    Args:
        name: The name of the logger.

    Returns:
        A configured logger instance.
    """
    return logging.getLogger(name)


def configure_logging(
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO",
) -> None:
    """Configure logging for MCP.

    Configures only the ``mcp`` namespace logger so that application-level
    logging configuration is not overridden.  Per the Python logging docs,
    library code should never call ``logging.basicConfig()`` or add handlers
    to the root logger.

    Args:
        level: The log level to use.
    """
    mcp_logger = logging.getLogger(_MCP_LOGGER_NAME)
    mcp_logger.setLevel(level)

    # Avoid adding duplicate handlers on repeated calls.
    if mcp_logger.handlers:
        return

    try:
        from rich.console import Console
        from rich.logging import RichHandler

        handler: logging.Handler = RichHandler(
            console=Console(stderr=True), rich_tracebacks=True
        )
    except ImportError:  # pragma: no cover
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))

    mcp_logger.addHandler(handler)
