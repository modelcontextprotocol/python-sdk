import logging
from typing import Any

import pytest

from mcp.server.mcpserver.utilities.logging import configure_logging, get_logger


def test_get_logger_returns_named_logger():
    logger = get_logger("mcp.test")

    assert logger is logging.getLogger("mcp.test")


def test_configure_logging_uses_rich_handler(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict[str, Any]] = []

    def fake_basic_config(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(logging, "basicConfig", fake_basic_config)

    configure_logging("WARNING")

    handlers = calls[0]["handlers"]
    assert calls == [
        {
            "level": "WARNING",
            "format": "%(message)s",
            "handlers": handlers,
        }
    ]
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.Handler)
