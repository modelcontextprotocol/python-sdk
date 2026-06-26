"""`docs/run/index.md`: every claim the page makes that is observable without a transport."""

from typing import Any

import pytest
from inline_snapshot import snapshot
from mcp_types import CallToolResult, TextContent

from docs_src.run import tutorial001, tutorial002, tutorial003
from mcp import Client
from mcp.server import MCPServer

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_the_run_call_is_guarded_so_importing_does_not_start_a_server() -> None:
    """tutorial001: `run()` sits under `__main__`, so the module imports cleanly and serves in-memory."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("search_books", {"query": "dune"})
        assert result == snapshot(
            CallToolResult(
                content=[TextContent(type="text", text="Found 3 books matching 'dune'.")],
                structured_content={"result": "Found 3 books matching 'dune'."},
            )
        )


async def test_the_transport_never_changes_what_the_server_is() -> None:
    """tutorial001/002/003 differ only in how they run: every client sees the identical tool."""
    async with (
        Client(tutorial001.mcp) as stdio_client,
        Client(tutorial002.mcp) as http_client,
        Client(tutorial003.mcp) as configured_client,
    ):
        baseline = await stdio_client.list_tools()
        assert baseline == await http_client.list_tools()
        assert baseline == await configured_client.list_tools()


def test_transport_options_are_not_constructor_options() -> None:
    """The page's warning: `port=` belongs to `run()`; the constructor rejects it."""
    options: dict[str, Any] = {"port": 3001}
    with pytest.raises(TypeError, match="unexpected keyword argument 'port'"):
        MCPServer("Bookshop", **options)


def test_settings_are_constructor_arguments_and_land_on_settings() -> None:
    """tutorial003: `log_level=` ends up on `mcp.settings`; the defaults are INFO and not-debug."""
    assert tutorial001.mcp.settings.log_level == "INFO"
    assert tutorial001.mcp.settings.debug is False
    assert tutorial003.mcp.settings.log_level == "DEBUG"
