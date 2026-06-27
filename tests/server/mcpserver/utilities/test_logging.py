import logging
from unittest.mock import MagicMock

import pytest
from rich.logging import RichHandler

from mcp.server.mcpserver.utilities.logging import configure_logging, get_logger


def test_get_logger_returns_named_logger():
    logger = get_logger("mcp.test")

    assert logger is logging.getLogger("mcp.test")


def test_configure_logging_uses_rich_handler(monkeypatch: pytest.MonkeyPatch):
    basic_config = MagicMock()
    monkeypatch.setattr(logging, "basicConfig", basic_config)

    configure_logging("DEBUG")

    basic_config.assert_called_once()
    kwargs = basic_config.call_args.kwargs
    assert kwargs["level"] == "DEBUG"
    assert kwargs["format"] == "%(message)s"
    assert len(kwargs["handlers"]) == 1
    assert isinstance(kwargs["handlers"][0], RichHandler)
