"""`docs/index.md` — the landing-page server does exactly what the page says it does."""

import pytest
from inline_snapshot import snapshot

from mcp_types import CallToolResult, TextContent, TextResourceContents

from docs_src.index.tutorial001 import mcp
from mcp import Client

# `pyproject.toml` globally downgrades `mcp.MCPDeprecationWarning` to *ignore* because the
# SDK still calls those methods internally. A documentation example must never lean on
# that allowance, so every test that runs one re-arms the warning as an error. This is a
# per-module mark, not a conftest hook, because `pytest_collection_modifyitems` receives
# every item in the session — a hook here would break unrelated tests across the repo.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_add_tool() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("add", {"a": 1, "b": 2})
        assert result == snapshot(
            CallToolResult(content=[TextContent(type="text", text="3")], structured_content={"result": 3})
        )


async def test_greeting_resource_template() -> None:
    async with Client(mcp) as client:
        result = await client.read_resource("greeting://World")
        assert result.contents == snapshot(
            [TextResourceContents(uri="greeting://World", mime_type="text/plain", text="Hello, World!")]
        )
