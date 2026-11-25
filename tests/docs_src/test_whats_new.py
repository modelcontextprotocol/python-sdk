"""`docs/whats-new.md`: the v2 half of the low-level before/after example, proved against the real SDK.

The v1 half of that example targets the 1.x line and cannot run here; it was
validated by running it verbatim against a real `mcp==1.28.1` install.
"""

import pytest
from mcp_types import INTERNAL_ERROR, INVALID_PARAMS, TextContent

from docs_src.whats_new import tutorial001
from mcp import Client, MCPError

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_the_advertised_schema_is_the_literal_dict() -> None:
    """Annotation 1: the schema is advertised to clients exactly as written."""
    async with Client(tutorial001.server) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.name == "search_books"
        assert tool.input_schema == {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }


async def test_a_valid_call_answers() -> None:
    """The example works end to end through the in-process `Client`."""
    async with Client(tutorial001.server) as client:
        result = await client.call_tool("search_books", {"query": "dune"})
        assert not result.is_error
        assert result.content == [TextContent(type="text", text="Found 3 books matching 'dune'.")]


async def test_arguments_are_not_validated_and_a_handler_exception_is_sanitized() -> None:
    """Annotations 1, 6, and 7, in one flow.

    A call missing the required `query` REACHES the handler (nothing validates
    arguments against `input_schema`; v1 rejected this call before the handler
    ran). The handler's own `KeyError` then comes back as a sanitized protocol
    error, never an `is_error=True` result the model could read. A call with no
    arguments at all exercises `params.arguments or {}` the same way.
    """
    async with Client(tutorial001.server) as client:
        with pytest.raises(MCPError) as excinfo:
            await client.call_tool("search_books", {"limit": 5})
        assert excinfo.value.code == INTERNAL_ERROR
        assert excinfo.value.message == "Internal server error"

        with pytest.raises(MCPError) as excinfo:
            await client.call_tool("search_books")
        assert excinfo.value.code == INTERNAL_ERROR
        assert excinfo.value.message == "Internal server error"


async def test_an_unknown_tool_is_a_deliberate_wire_error() -> None:
    """Annotation 5: a raised `MCPError` passes through with its code and message
    intact (the spec's answer for an unknown tool), unlike the sanitized path."""
    async with Client(tutorial001.server) as client:
        with pytest.raises(MCPError) as excinfo:
            await client.call_tool("shelve_book", {"query": "dune"})
        assert excinfo.value.code == INVALID_PARAMS
        assert excinfo.value.message == "Unknown tool: shelve_book"
