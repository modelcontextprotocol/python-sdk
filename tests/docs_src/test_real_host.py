"""`docs/get-started/real-host.md`: the one server every host section on the page launches, driven in memory."""

import pytest
from inline_snapshot import snapshot
from mcp_types import TextContent, TextResourceContents

from docs_src.real_host import tutorial001
from mcp import Client

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_the_host_sees_exactly_what_the_decorators_registered() -> None:
    """tutorial001: `tools/list` is what a host hands its model. Name, description, and schema come from the code."""
    async with Client(tutorial001.mcp) as client:
        search, get = (await client.list_tools()).tools
        assert search.name == "search_books"
        assert search.description == "Search the catalog by title or author."
        assert search.input_schema == snapshot(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"query": {"title": "Query", "type": "string"}},
                "required": ["query"],
                "title": "search_booksArguments",
            }
        )
        assert get.name == "get_author"


async def test_a_tool_call_round_trips_the_way_a_host_drives_it() -> None:
    """tutorial001: `tools/call` sends arguments in; the function's return value comes back as the result."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("search_books", {"query": "gibson"})
        assert not result.is_error
        assert result.structured_content == {"result": ["Neuromancer"]}

        author = await client.call_tool("get_author", {"title": "Dune"})
        assert author.content == [TextContent(type="text", text="Frank Herbert")]


async def test_the_resource_a_host_can_attach_to_context() -> None:
    """tutorial001: `catalog://titles` has no parameter, so it is a concrete, listable, readable resource."""
    async with Client(tutorial001.mcp) as client:
        (resource,) = (await client.list_resources()).resources
        assert str(resource.uri) == "catalog://titles"
        result = await client.read_resource("catalog://titles")
        assert result.contents == [
            TextResourceContents(
                uri="catalog://titles",
                mime_type="text/plain",
                text="Dune\nNeuromancer\nThe Left Hand of Darkness",
            )
        ]
