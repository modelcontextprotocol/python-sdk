"""`docs/handlers/logging.md`: every claim the page makes, proved against the real SDK."""

import logging

import pytest
from inline_snapshot import snapshot
from mcp_types import CallToolResult, TextContent

from docs_src.logging import tutorial001
from mcp import Client
from mcp.server import MCPServer

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_the_tool_logs_through_the_standard_library(caplog: pytest.LogCaptureFixture) -> None:
    """tutorial001: `logger.info(...)` inside a tool emits an ordinary stdlib record named after the module."""
    caplog.set_level(logging.INFO)
    async with Client(tutorial001.mcp) as client:
        await client.call_tool("search_books", {"query": "dune"})
    (record,) = list(filter(lambda r: r.name == tutorial001.logger.name, caplog.records))
    assert record.levelname == "INFO"
    assert record.getMessage() == "Searching for 'dune'"


async def test_the_log_line_never_reaches_the_client() -> None:
    """tutorial001: the result is only the return value. Log output is invisible to the model."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("search_books", {"query": "dune"})
        assert result == snapshot(
            CallToolResult(
                content=[TextContent(type="text", text="Found 3 books matching 'dune'.")],
                structured_content={"result": "Found 3 books matching 'dune'."},
            )
        )


def test_log_level_configures_the_root_logger() -> None:
    """`MCPServer(log_level=...)` calls `logging.basicConfig()` when nothing has configured logging yet."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    root.handlers = []
    try:
        MCPServer("Bookshop", log_level="DEBUG")
        assert root.level == logging.DEBUG
        assert len(root.handlers) == 1
    finally:
        root.handlers, root.level = handlers, level


def test_an_existing_logging_configuration_wins() -> None:
    """`logging.basicConfig()` is a no-op once a handler is installed, so your own setup is not overridden."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    root.handlers, root.level = [logging.NullHandler()], logging.WARNING
    try:
        MCPServer("Bookshop", log_level="DEBUG")
        assert root.level == logging.WARNING
        assert len(root.handlers) == 1
    finally:
        root.handlers, root.level = handlers, level
