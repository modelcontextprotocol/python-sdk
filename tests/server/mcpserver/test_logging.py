import logging
from collections.abc import Iterator

import pytest

from mcp.server.mcpserver.utilities.logging import configure_logging

LoggingState = tuple[logging.Logger, logging.Logger]


@pytest.fixture
def restore_logging_state() -> Iterator[LoggingState]:
    root_logger = logging.getLogger()
    mcp_logger = logging.getLogger("mcp")
    mcp_handlers = list(mcp_logger.handlers)
    root_level = root_logger.level
    mcp_level = mcp_logger.level
    mcp_propagate = mcp_logger.propagate

    mcp_logger.handlers.clear()

    try:
        yield root_logger, mcp_logger
    finally:
        mcp_logger.handlers[:] = mcp_handlers
        root_logger.setLevel(root_level)
        mcp_logger.setLevel(mcp_level)
        mcp_logger.propagate = mcp_propagate


def test_configure_logging_does_not_install_root_handler(restore_logging_state: LoggingState):
    root_logger, mcp_logger = restore_logging_state
    root_handlers = list(root_logger.handlers)
    root_logger.setLevel(logging.WARNING)

    configure_logging("INFO")

    assert root_logger.handlers == root_handlers
    assert root_logger.level == logging.WARNING
    assert len(mcp_logger.handlers) == 1
    assert mcp_logger.level == logging.INFO
    assert mcp_logger.propagate is True


def test_configure_logging_reuses_mcp_handler(restore_logging_state: LoggingState):
    _, mcp_logger = restore_logging_state

    configure_logging("INFO")
    handlers: list[logging.Handler] = list(mcp_logger.handlers)
    configure_logging("DEBUG")

    assert mcp_logger.handlers == handlers
    assert mcp_logger.level == logging.DEBUG
    assert mcp_logger.propagate is True
