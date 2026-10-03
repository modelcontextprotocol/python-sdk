"""`docs/client/index.md`: every claim the page makes, proved against the real SDK.

`tutorial001` is the page's `server.py`. The other snippets are `client.py` programs that reach it
by URL, so each test drives the same calls in-process against `tutorial001.mcp` instead.
"""

import pytest
from inline_snapshot import snapshot
from mcp_types import Prompt, PromptArgument, PromptReference, TextContent, TextResourceContents, Tool

from docs_src.client import tutorial001, tutorial007
from mcp import Client, MCPDeprecationWarning, MCPError
from mcp.shared.metadata_utils import get_display_name

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_connected_properties_are_populated_inside_the_block() -> None:
    """tutorial001_client's four prints, in-process against server.py: server_info, capabilities, protocol_version
    and instructions are just there, and a capability the server lacks is None."""
    async with Client(tutorial001.mcp) as client:
        assert client.server_info is not None
        assert client.server_info.name == "Bookshop"
        assert client.protocol_version == "2026-07-28"
        assert client.instructions == "Search the catalog before recommending a book."
        assert client.server_capabilities.tools is not None
        assert client.server_capabilities.resources is not None
        assert client.server_capabilities.prompts is not None
        assert client.server_capabilities.completions is not None
        assert client.server_capabilities.logging is None


async def test_a_client_is_not_reusable_after_the_block_ends() -> None:
    """The lifecycle bullet: `async with` is the whole lifecycle. Construct a new Client per connection."""
    client = Client(tutorial001.mcp)
    async with client:
        assert client.server_info is not None
        assert client.server_info.name == "Bookshop"
    with pytest.raises(RuntimeError, match="cannot reenter"):
        await client.__aenter__()


async def test_list_tools_returns_the_full_definition() -> None:
    """tutorial002's listing, in-process: each tool carries its name, title, description and the derived
    input schema, and a tool registered without `title=` lists with title None."""
    async with Client(tutorial001.mcp) as client:
        (search, lookup) = (await client.list_tools()).tools
        assert search.name == "search_books"
        assert search.title == "Search the catalog"
        assert search.description == "Search the catalog by title or author."
        assert search.input_schema == snapshot(
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
        assert lookup.name == "lookup_book"
        assert lookup.title is None


def test_get_display_name_prefers_the_title() -> None:
    """The `!!! tip`: get_display_name returns the title when there is one and the name when there isn't."""
    titled = Tool(name="search_books", title="Search the catalog", input_schema={"type": "object"})
    untitled = Tool(name="search_books", input_schema={"type": "object"})
    assert get_display_name(titled) == "Search the catalog"
    assert get_display_name(untitled) == "search_books"


async def test_call_tool_result_has_three_things_to_read() -> None:
    """tutorial003's call, in-process: content for the model, structured_content for code, is_error for both."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("lookup_book", {"title": "Dune"})
        assert not result.is_error
        (block,) = result.content
        assert isinstance(block, TextContent)
        assert block.text == '{\n  "title": "Dune",\n  "author": "Frank Herbert",\n  "year": 1965\n}'
        assert result.structured_content == {"title": "Dune", "author": "Frank Herbert", "year": 1965}


async def test_a_raising_tool_is_a_result_not_an_exception() -> None:
    """The `!!! check`: the ToolError's message comes back in content with is_error=True."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("lookup_book", {"title": "Solaris"})
        assert result.is_error
        (block,) = result.content
        assert isinstance(block, TextContent)
        assert block.text == "Error executing tool lookup_book: No book titled 'Solaris' in the catalog."
        assert result.structured_content is None


async def test_an_unknown_tool_name_is_a_result_not_an_exception() -> None:
    """The `!!! warning`: a tool the server doesn't have comes back as is_error=True, not as MCPError."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("does_not_exist", {})
        assert result.is_error
        (block,) = result.content
        assert isinstance(block, TextContent)
        assert block.text == "Unknown tool: does_not_exist"
        assert result.structured_content is None


async def test_resources_and_templates_are_two_separate_lists() -> None:
    """tutorial004's two listings, in-process: concrete resources and parameterised templates come back
    from different verbs."""
    async with Client(tutorial001.mcp) as client:
        (resource,) = (await client.list_resources()).resources
        assert resource.uri == "catalog://genres"
        (template,) = (await client.list_resource_templates()).resource_templates
        assert template.uri_template == "catalog://genres/{genre}"


async def test_read_resource_fills_in_a_template() -> None:
    """tutorial004's read, in-process: read_resource takes a plain str URI, the server matches it to the
    template, and the contents narrow with isinstance."""
    async with Client(tutorial001.mcp) as client:
        (contents,) = (await client.read_resource("catalog://genres/poetry")).contents
        assert isinstance(contents, TextResourceContents)
        assert contents.text == "3 books filed under poetry."


async def test_resource_subscriptions_are_listen_based_on_the_modern_wire() -> None:
    """The Resources section: at 2026-07-28 `resources.subscribe` is True (served via
    subscriptions/listen) while the legacy subscribe_resource verb answers -32601."""
    async with Client(tutorial001.mcp) as client:
        assert client.server_capabilities.resources is not None
        assert client.server_capabilities.resources.subscribe is True
        with pytest.raises(MCPError) as exc_info:
            # The verb is itself deprecated; the modern wire also rejects it.
            with pytest.warns(MCPDeprecationWarning, match="use Client.listen"):
                await client.subscribe_resource("catalog://genres")  # pyright: ignore[reportDeprecated]
        assert exc_info.value.error.code == -32601
        assert exc_info.value.error.message == "Method not found"


async def test_list_prompts_describes_the_arguments() -> None:
    """tutorial005's listing, in-process: a listed prompt carries its name, title and the arguments it needs."""
    async with Client(tutorial001.mcp) as client:
        (prompt,) = (await client.list_prompts()).prompts
        assert prompt == snapshot(
            Prompt(
                name="recommend",
                title="Recommend a book",
                description="Ask for a recommendation in a genre.",
                arguments=[PromptArgument(name="genre", required=True)],
            )
        )


async def test_get_prompt_renders_the_messages() -> None:
    """tutorial005's render, in-process: get_prompt returns the messages a host hands to the model."""
    async with Client(tutorial001.mcp) as client:
        result = await client.get_prompt("recommend", {"genre": "poetry"})
        (message,) = result.messages
        assert message.role == "user"
        assert message.content == TextContent(
            type="text", text="Recommend one poetry book from the catalog and say why."
        )


async def test_complete_suggests_values_for_an_argument() -> None:
    """tutorial006's call, in-process: complete takes a ref and a name/value pair and returns the matching
    values."""
    async with Client(tutorial001.mcp) as client:
        result = await client.complete(
            ref=PromptReference(type="ref/prompt", name="recommend"),
            argument={"name": "genre", "value": "p"},
        )
        assert result.completion.values == ["poetry"]


async def test_the_pagination_loop_collects_every_tool_from_a_single_page_server() -> None:
    """tutorial007's `list_all_tools`, driven in-process against server.py: MCPServer answers in one page,
    so the loop ends on the first `next_cursor is None` with every tool collected."""
    async with Client(tutorial001.mcp) as client:
        tools = await tutorial007.list_all_tools(client)
        assert [tool.name for tool in tools] == ["search_books", "lookup_book"]
        assert (await client.list_tools(cursor=None)).next_cursor is None


async def test_raise_exceptions_is_a_constructor_flag() -> None:
    """The `## In tests` section: `raise_exceptions=True` is accepted by the in-memory Client."""
    async with Client(tutorial001.mcp, raise_exceptions=True) as client:
        result = await client.call_tool("search_books", {"query": "dune"})
        assert result.structured_content == {"result": "Found 3 books matching 'dune' (showing up to 10)."}
