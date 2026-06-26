"""`docs/tutorial/testing.md`: the page's own test, run for real.

The page shows this test against a `server.py` next to it; here the import path
is the only difference.
"""

import pytest
from inline_snapshot import snapshot
from mcp_types import CallToolResult, TextContent

from docs_src.testing.tutorial001 import mcp
from mcp import Client

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_call_add_tool() -> None:
    async with Client(mcp, raise_exceptions=True) as client:
        result = await client.call_tool("add", {"a": 1, "b": 2})
        assert result == snapshot(
            CallToolResult(content=[TextContent(type="text", text="3")], structured_content={"result": 3})
        )
