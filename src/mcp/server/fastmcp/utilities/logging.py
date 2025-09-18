"""Logging utilities for FastMCP."""

import logging
from collections.abc import Mapping
from typing import Any, Literal


def get_logger(name: str) -> logging.Logger:
    """Get a logger nested under MCPnamespace.

    Args:
        name: the name of the logger, which will be prefixed with 'FastMCP.'

    Returns:
        a configured logger instance
    """
    return logging.getLogger(name)


def configure_logging(
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO",
) -> None:
    """Configure logging for MCP.

    Args:
        level: the log level to use
    """
    handlers: list[logging.Handler] = []
    try:
        from rich.console import Console
        from rich.logging import RichHandler

        handlers.append(RichHandler(console=Console(stderr=True), rich_tracebacks=True))
    except ImportError:
        pass

    if not handlers:
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=handlers,
    )


# ---------------------------------------------------------------------------
# Helper – redact sensitive data before logging
# ---------------------------------------------------------------------------


def redact_sensitive_data(
    data: Mapping[str, Any] | None,
    sensitive_keys: set[str] | None = None,
) -> Mapping[str, Any] | None:
    """Return a shallow copy with sensitive values replaced by "***".

    This shared helper can be used across the code-base (e.g. the transparent
    OAuth proxy) to ensure we treat secrets consistently.

    Parameters
    ----------
    data:
        Original mapping (typically request/response payload).  If *None* the
        function simply returns *None*.
    sensitive_keys:
        Optional set of keys that should be hidden; defaults to a common list
        of OAuth-related secrets.
    """

    if data is None:
        return None

    sensitive_keys = sensitive_keys or {
        "client_secret",
        "authorization",
        "access_token",
        "refresh_token",
        "code",
    }

    redacted: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in sensitive_keys:
            # Show a short prefix of auth codes; redact everything else
            if key.lower() == "code" and isinstance(value, str):
                redacted[key] = value[:8] + "..." if len(value) > 8 else "***"
            else:
                redacted[key] = "***"
        else:
            redacted[key] = value

    return redacted
