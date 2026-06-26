"""`docs/tutorial/progress.md`: every claim the page makes, proved against the real SDK."""

import inspect

import pytest
from mcp_types import TextContent

from docs_src.progress import tutorial001, tutorial002
from mcp import Client

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]

URLS = ["https://example.com/a.json", "https://example.com/b.json"]


async def test_context_parameter_is_invisible_to_the_model() -> None:
    """tutorial001: `ctx` comes from the type hint and never reaches the input schema."""
    async with Client(tutorial001.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.input_schema["properties"] == {
            "urls": {"items": {"type": "string"}, "title": "Urls", "type": "array"}
        }
        assert tool.input_schema["required"] == ["urls"]


async def test_each_report_becomes_one_callback_invocation_in_order() -> None:
    """tutorial001: `progress_callback` receives every `(progress, total, message)` the tool reported."""
    updates: list[tuple[float, float | None, str | None]] = []

    async def show(progress: float, total: float | None, message: str | None) -> None:
        updates.append((progress, total, message))

    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("import_catalog", {"urls": URLS}, progress_callback=show)
        assert updates == [
            (1, 2, "Imported https://example.com/a.json"),
            (2, 2, "Imported https://example.com/b.json"),
        ]
    assert result.content == [TextContent(type="text", text="Imported 2 records.")]
    assert result.structured_content == {"result": "Imported 2 records."}


async def test_without_a_callback_report_progress_is_a_no_op() -> None:
    """The `!!! check`: omit `progress_callback` and the tool runs to the same result, no error."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("import_catalog", {"urls": URLS})
        assert not result.is_error
        assert result.structured_content == {"result": "Imported 2 records."}


def test_progress_callback_is_per_call_not_per_client() -> None:
    """The `!!! warning`: `call_tool` takes `progress_callback`; the `Client` constructor does not."""
    assert "progress_callback" in inspect.signature(Client.call_tool).parameters
    assert "progress_callback" not in inspect.signature(Client.__init__).parameters


async def test_omitting_total_reaches_the_callback_as_none() -> None:
    """tutorial002: a report without `total` arrives as `total=None`: activity, not a percentage."""
    updates: list[tuple[float, float | None, str | None]] = []

    async def show(progress: float, total: float | None, message: str | None) -> None:
        updates.append((progress, total, message))

    async with Client(tutorial002.mcp) as client:
        result = await client.call_tool("import_feed", {"feed_url": "https://example.com/feed"}, progress_callback=show)
        assert updates == [
            (1, None, "Imported https://example.com/feed#Dune"),
            (2, None, "Imported https://example.com/feed#Neuromancer"),
            (3, None, "Imported https://example.com/feed#Hyperion"),
        ]
    assert result.structured_content == {"result": "Imported 3 records."}
