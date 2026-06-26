"""`docs/tutorial/handling-errors.md`: every claim the page makes, proved against the real SDK."""

import pytest
from mcp_types import INVALID_PARAMS, ErrorData, TextContent, TextResourceContents

from docs_src.handling_errors import tutorial001, tutorial002, tutorial003
from mcp import Client, MCPError

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_a_plain_exception_becomes_a_tool_error_the_model_reads() -> None:
    """tutorial001: any non-`MCPError` exception comes back as `is_error=True` with the message in `content`."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("get_author", {"title": "Nothing"})
        assert result.is_error
        assert result.content == [
            TextContent(type="text", text="Error executing tool get_author: No book titled 'Nothing' in the catalog.")
        ]
        assert result.structured_content is None


async def test_a_title_the_catalog_knows_is_an_ordinary_result() -> None:
    """tutorial001: the non-raising path is a plain `is_error=False` result."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("get_author", {"title": "Dune"})
        assert not result.is_error
        assert result.structured_content == {"result": "Frank Herbert"}


async def test_a_bad_argument_never_reaches_the_function() -> None:
    """tutorial001: schema validation rejects the call before `get_author` runs, as the same kind of tool error."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("get_author", {"title": 42})
        assert result.is_error
        assert isinstance(result.content[0], TextContent)
        assert "Input should be a valid string" in result.content[0].text


async def test_mcp_error_makes_the_call_itself_fail() -> None:
    """tutorial002: `MCPError` is not caught. It surfaces as a JSON-RPC error, with `code` and `message` intact."""
    async with Client(tutorial002.mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("get_author", {"title": "Nothing"})
        assert exc_info.value.code == INVALID_PARAMS
        assert exc_info.value.message == "No book titled 'Nothing' in the catalog."


async def test_mcp_error_only_fires_on_the_raising_path() -> None:
    """tutorial002: a title the catalog knows still returns a normal result."""
    async with Client(tutorial002.mcp) as client:
        result = await client.call_tool("get_author", {"title": "Dune"})
        assert not result.is_error
        assert result.structured_content == {"result": "Frank Herbert"}


async def test_resource_not_found_error_maps_to_invalid_params() -> None:
    """tutorial003: `ResourceNotFoundError` from a template handler is `-32602` with the URI in `data`."""
    async with Client(tutorial003.mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("books://Nothing")
        assert exc_info.value.error == ErrorData(
            code=INVALID_PARAMS,
            message="No book titled 'Nothing' in the catalog.",
            data={"uri": "books://Nothing"},
        )


async def test_raise_exceptions_does_not_turn_a_tool_error_into_a_traceback() -> None:
    """The closing `!!! info`: even `raise_exceptions=True` leaves a failing tool as the `is_error=True` result."""
    async with Client(tutorial001.mcp, raise_exceptions=True) as client:
        result = await client.call_tool("get_author", {"title": "Nothing"})
        assert result.is_error
        assert result.content == [
            TextContent(type="text", text="Error executing tool get_author: No book titled 'Nothing' in the catalog.")
        ]


async def test_a_title_the_template_knows_reads_normally() -> None:
    """tutorial003: the non-raising path resolves the template and returns text contents."""
    async with Client(tutorial003.mcp) as client:
        result = await client.read_resource("books://Dune")
        (contents,) = result.contents
        assert isinstance(contents, TextResourceContents)
        assert contents.text == "Dune by Frank Herbert"
