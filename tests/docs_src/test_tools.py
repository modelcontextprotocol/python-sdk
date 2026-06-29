"""`docs/tutorial/tools.md`: every claim the page makes, proved against the real SDK."""

import pytest
from inline_snapshot import snapshot
from mcp_types import TextContent, ToolAnnotations

from docs_src.tools import tutorial001, tutorial002, tutorial003, tutorial004, tutorial005
from mcp import Client

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_signature_becomes_the_schema() -> None:
    async with Client(tutorial001.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.name == "search_books"
        assert tool.description == "Search the catalog by title or author."
        assert tool.input_schema == snapshot(
            {
                "type": "object",
                "properties": {
                    "query": {"title": "Query", "type": "string"},
                    "limit": {"title": "Limit", "type": "integer"},
                },
                "required": ["query", "limit"],
                "title": "search_booksArguments",
            }
        )


async def test_call_returns_text_and_structured_content() -> None:
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("search_books", {"query": "dune", "limit": 5})
        assert not result.is_error
        assert result.content == [TextContent(type="text", text="Found 3 books matching 'dune' (showing up to 5).")]
        assert result.structured_content == {"result": "Found 3 books matching 'dune' (showing up to 5)."}


async def test_default_value_makes_the_argument_optional() -> None:
    """The whole schema is pinned because the page quotes it verbatim."""
    async with Client(tutorial002.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.input_schema == snapshot(
            {
                "type": "object",
                "properties": {
                    "query": {"title": "Query", "type": "string"},
                    "limit": {"default": 10, "title": "Limit", "type": "integer"},
                },
                "required": ["query"],
                "title": "search_booksArguments",
            }
        )
        result = await client.call_tool("search_books", {"query": "dune"})
        assert result.structured_content == {"result": "Found 3 books matching 'dune' (showing up to 10)."}


async def test_field_constraints_land_in_the_schema() -> None:
    async with Client(tutorial003.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        props = tool.input_schema["properties"]
        assert props["query"]["description"] == "Title or author to search for."
        assert props["limit"] == snapshot(
            {
                "default": 10,
                "description": "Maximum number of results.",
                "maximum": 50,
                "minimum": 1,
                "title": "Limit",
                "type": "integer",
            }
        )
        assert props["genre"]["anyOf"][0]["enum"] == ["fiction", "non-fiction", "poetry"]


async def test_constraint_violation_is_an_error_the_model_can_read() -> None:
    async with Client(tutorial003.mcp) as client:
        result = await client.call_tool("search_books", {"query": "dune", "limit": 999})
        assert result.is_error
        assert isinstance(result.content[0], TextContent)
        assert "less than or equal to 50" in result.content[0].text


async def test_pydantic_model_parameter() -> None:
    async with Client(tutorial004.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.input_schema["$defs"]["Book"]["required"] == ["title", "author", "year"]
        book = {"title": "Dune", "author": "Frank Herbert", "year": 1965}
        result = await client.call_tool("add_book", {"book": book})
        assert result.structured_content == {"result": "Added 'Dune' by Frank Herbert (1965)."}


async def test_title_and_annotations() -> None:
    async with Client(tutorial005.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.title == "Search the catalog"
        assert tool.annotations == ToolAnnotations(read_only_hint=True, open_world_hint=False)
