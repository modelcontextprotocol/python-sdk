"""`docs/advanced/low-level-server.md`: every claim the page makes, proved against the real SDK."""

import pytest
from inline_snapshot import snapshot
from mcp_types import INTERNAL_ERROR, CallToolRequestParams, CallToolResult, ErrorData, RequestParams, TextContent

from docs_src.lowlevel import tutorial001, tutorial002, tutorial003, tutorial004, tutorial005, tutorial006
from mcp import Client, MCPError
from mcp.server import Server, ServerRequestContext

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_the_input_schema_on_the_wire_is_the_dict_you_wrote() -> None:
    async with Client(tutorial001.server) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.name == "search_books"
        assert tool.description == "Search the catalog by title or author."
        assert tool.input_schema == snapshot(
            {
                "type": "object",
                "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                "required": ["query", "limit"],
            }
        )
        assert tool.output_schema is None


async def test_the_client_does_not_care_which_server_class_it_connects_to() -> None:
    async with Client(tutorial001.server) as client:
        result = await client.call_tool("search_books", {"query": "dune", "limit": 5})
        assert not result.is_error
        assert result.content == [TextContent(type="text", text="Found 3 books matching 'dune' (showing up to 5).")]
        assert result.structured_content is None


async def test_only_the_handlers_you_passed_become_capabilities() -> None:
    async with Client(tutorial001.server) as client:
        assert client.server_capabilities.model_dump(exclude_none=True) == snapshot({"tools": {"list_changed": False}})


async def test_arguments_are_not_validated_against_your_schema() -> None:
    async with Client(tutorial001.server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("search_books", {"query": "dune"})
    assert exc_info.value.error == ErrorData(code=INTERNAL_ERROR, message="Internal server error", data=None)


async def test_one_handler_routes_every_tool() -> None:
    async with Client(tutorial002.server) as client:
        assert [tool.name for tool in (await client.list_tools()).tools] == ["search_books", "add_book"]
        result = await client.call_tool("add_book", {"title": "Dune", "author": "Frank Herbert", "year": 1965})
        assert result.content == [TextContent(type="text", text="Added 'Dune' by Frank Herbert (1965).")]


async def test_an_unknown_tool_name_becomes_a_protocol_error_not_a_tool_error() -> None:
    async with Client(tutorial002.server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("does_not_exist", {})
    assert exc_info.value.error == ErrorData(code=INTERNAL_ERROR, message="Internal server error", data=None)


async def test_output_schema_and_structured_content_are_both_yours_to_build() -> None:
    async with Client(tutorial003.server) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.output_schema == snapshot(
            {
                "type": "object",
                "properties": {"matches": {"type": "integer"}, "query": {"type": "string"}},
                "required": ["matches", "query"],
            }
        )
        result = await client.call_tool("search_books", {"query": "dune", "limit": 5})
        assert result.content == [TextContent(type="text", text="Found 3 books matching 'dune'.")]
        assert result.structured_content == {"matches": 3, "query": "dune"}


async def test_the_client_checks_the_schema_you_promised() -> None:
    async def promise_breaker(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        return CallToolResult(content=[TextContent(type="text", text="oops")], structured_content={"matches": "three"})

    lying = Server("Bookshop", on_list_tools=tutorial003.list_tools, on_call_tool=promise_breaker)
    async with Client(lying) as client:
        with pytest.raises(RuntimeError, match="Invalid structured content returned by tool search_books"):
            await client.call_tool("search_books", {"query": "dune", "limit": 5})


async def test_meta_reaches_the_client_application() -> None:
    async with Client(tutorial004.server) as client:
        result = await client.call_tool("search_books", {"query": "dune", "limit": 5})
        assert result.meta == {"bookshop/record_ids": ["bk_17", "bk_42", "bk_99"]}
        assert result.model_dump(by_alias=True, exclude_none=True) == snapshot(
            {
                "_meta": {"bookshop/record_ids": ["bk_17", "bk_42", "bk_99"]},
                "content": [{"type": "text", "text": "Found 3 books matching 'dune'."}],
                "structuredContent": {"matches": 3, "query": "dune"},
                "isError": False,
                "resultType": "complete",
            }
        )


async def test_the_lifespan_object_reaches_every_handler_with_its_type() -> None:
    async with Client(tutorial005.server) as client:
        result = await client.call_tool("search_books", {"query": "dune"})
        assert result.content == [TextContent(type="text", text="Found 3 books: Dune, Dune Messiah, Children of Dune.")]


async def test_add_request_handler_registers_a_method_the_constructor_does_not_know() -> None:
    entry = tutorial006.server.get_request_handler("bookshop/reindex")
    assert entry is not None
    assert entry.params_type is tutorial006.ReindexParams
    assert tutorial006.server.get_request_handler("bookshop/burn") is None


async def test_a_custom_method_never_changes_the_advertised_capabilities() -> None:
    async with Client(tutorial006.server) as client:
        assert client.server_capabilities.model_dump(exclude_none=True) == snapshot({"tools": {"list_changed": False}})


def test_initialize_is_reserved() -> None:
    server = Server("Bookshop")

    async def grab_the_handshake(ctx: ServerRequestContext, params: RequestParams) -> None:
        raise NotImplementedError

    with pytest.raises(ValueError, match="'initialize' is handled by the server runner"):
        server.add_request_handler("initialize", RequestParams, grab_the_handshake)
