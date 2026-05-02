"""Test for issue #2527: MCPServer.__init__ must not pollute the root logger.

Regression test verifying that:
1. Instantiating MCPServer does NOT add any handlers to the root logger.
2. configure_logging() targets the "mcp" logger, not the root logger.
3. configure_logging() is idempotent (calling it twice doesn't add a second handler).
4. The "mcp" logger does not propagate to the root logger after configure_logging().
"""

import logging

import pytest

from mcp.server.mcpserver.utilities.logging import configure_logging


def test_configure_logging_does_not_touch_root_logger():
    """configure_logging() must not add handlers to the root logger."""
    root = logging.getLogger()
    handlers_before = list(root.handlers)

    # Call explicitly; MCPServer.__init__ calls this too.
    configure_logging()

    assert root.handlers == handlers_before, (
        "configure_logging() added a handler to the root logger, which pollutes "
        "all third-party loggers and can deadlock stdio servers under back-pressure."
    )


def test_configure_logging_adds_handler_to_mcp_logger():
    """configure_logging() must add a handler to the 'mcp' logger."""
    mcp_logger = logging.getLogger("mcp")
    # Remove any handlers that may have been added by a previous test run.
    mcp_logger.handlers.clear()
    mcp_logger.propagate = True  # reset

    configure_logging()

    assert mcp_logger.handlers, "configure_logging() did not add any handler to the 'mcp' logger."


def test_configure_logging_sets_propagate_false():
    """The 'mcp' logger must not propagate to root after configure_logging()."""
    mcp_logger = logging.getLogger("mcp")
    mcp_logger.handlers.clear()
    mcp_logger.propagate = True  # reset

    configure_logging()

    assert not mcp_logger.propagate, (
        "mcp logger propagates to root; any INFO log from mcp can reach third-party "
        "root handlers and cause back-pressure on stdio stderr."
    )


def test_configure_logging_is_idempotent():
    """Calling configure_logging() twice must not add a second handler."""
    mcp_logger = logging.getLogger("mcp")
    mcp_logger.handlers.clear()
    mcp_logger.propagate = True  # reset

    configure_logging()
    handler_count_after_first = len(mcp_logger.handlers)

    configure_logging()
    handler_count_after_second = len(mcp_logger.handlers)

    assert handler_count_after_first == handler_count_after_second, (
        "configure_logging() is not idempotent: calling it twice added extra handlers."
    )


def test_mcpserver_init_does_not_pollute_root_logger():
    """MCPServer() must not add handlers to the root logger."""
    # Remove any mcp logger handlers first so configure_logging runs fresh.
    mcp_logger = logging.getLogger("mcp")
    mcp_logger.handlers.clear()

    root = logging.getLogger()
    handlers_before = list(root.handlers)

    # Import here to avoid side-effects at module import time.
    from mcp.server.mcpserver.server import MCPServer

    MCPServer("test-server")

    assert root.handlers == handlers_before, (
        "MCPServer.__init__ added a handler to the root logger. "
        "This pollutes all third-party loggers and can deadlock stdio servers."
    )
