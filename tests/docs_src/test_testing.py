"""`docs/get-started/testing.md`: the page's own test, run for real.

The page shows this test against a `server.py` next to it; here the import path
is the only difference.
"""

import pytest
from inline_snapshot import snapshot
from mcp_types import INTERNAL_ERROR, CallToolResult, TextContent

from docs_src.testing import tutorial001, tutorial002
from mcp import Client, MCPError
from tests.docs_src._helpers import strip_server_info

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_call_add_tool() -> None:
    """tutorial001: the page's fixture-shaped happy path with `raise_exceptions=True`."""
    async with Client(tutorial001.mcp, raise_exceptions=True) as client:
        result = await client.call_tool("add", {"a": 1, "b": 2})
        result = strip_server_info(result, tutorial001.mcp)
        assert result == snapshot(
            CallToolResult(content=[TextContent(type="text", text="3")], structured_content={"result": 3})
        )


async def test_raise_exceptions_true_chains_the_original_handler_error() -> None:
    """The `Why raise_exceptions=True?` section: still `MCPError`, but message and `__cause__` are real."""
    async with Client(tutorial002.server, raise_exceptions=True) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("search_books", {"query": "dune"})
    assert exc_info.value.error.code == INTERNAL_ERROR
    assert isinstance(exc_info.value.__cause__, KeyError)
    assert exc_info.value.__cause__.args == ("limit",)


async def test_raise_exceptions_false_sanitises_the_handler_error() -> None:
    """Without the flag, the same low-level crash is the opaque `"Internal server error"`."""
    async with Client(tutorial002.server, raise_exceptions=False) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("search_books", {"query": "dune"})
    assert exc_info.value.error.code == INTERNAL_ERROR
    assert exc_info.value.error.message == "Internal server error"
    assert exc_info.value.__cause__ is None
