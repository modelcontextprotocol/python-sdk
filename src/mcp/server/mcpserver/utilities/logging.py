"""Logging utilities for MCPServer."""

import logging


def get_logger(name: str) -> logging.Logger:
    """Get a logger nested under MCP namespace.

    Args:
        name: the name of the logger

    Returns:
        a configured logger instance
    """
    return logging.getLogger(name)
