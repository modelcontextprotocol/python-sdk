"""`docs/handlers/context.md`: every claim the page makes, proved against the real SDK."""

import re

import pytest
from inline_snapshot import snapshot
from mcp_types import TextContent, TextResourceContents, ToolListChangedNotification

from docs_src.context import tutorial001, tutorial002, tutorial003
from mcp import Client

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_the_context_parameter_is_not_in_the_input_schema() -> None:
    """tutorial001: the injected `Context` never appears in the schema the model sees."""
    async with Client(tutorial001.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.input_schema == snapshot(
            {
                "type": "object",
                "properties": {"query": {"title": "Query", "type": "string"}},
                "required": ["query"],
                "title": "search_booksArguments",
            }
        )


async def test_every_request_gets_its_own_context() -> None:
    """tutorial001: `ctx.request_id` identifies the request being served, so it changes per call."""
    async with Client(tutorial001.mcp) as client:
        first = await client.call_tool("search_books", {"query": "dune"})
        second = await client.call_tool("search_books", {"query": "dune"})
        assert isinstance(first.content[0], TextContent)
        assert isinstance(second.content[0], TextContent)
        assert re.fullmatch(r"\[request \d+\] Found 3 books matching 'dune'\.", first.content[0].text)
        assert first.content[0].text != second.content[0].text


async def test_a_tool_reads_the_servers_own_resource() -> None:
    """tutorial002: `ctx.read_resource` resolves the URI through the same registry `resources/read` uses."""
    async with Client(tutorial002.mcp) as client:
        result = await client.call_tool("describe_catalog", {})
        assert not result.is_error
        assert result.content == [
            TextContent(type="text", text="The catalog is organised into: fiction, non-fiction, poetry")
        ]
        (contents,) = (await client.read_resource("catalog://genres")).contents
        assert isinstance(contents, TextResourceContents)
        assert contents.text == "fiction, non-fiction, poetry"


async def test_a_context_only_tool_takes_no_arguments() -> None:
    """tutorial002: a tool whose only parameter is the `Context` has an empty input schema."""
    async with Client(tutorial002.mcp) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        assert tools["describe_catalog"].input_schema == snapshot(
            {"type": "object", "properties": {}, "title": "describe_catalogArguments"}
        )


async def test_register_a_tool_at_runtime_and_notify_the_client() -> None:
    """tutorial003: `mcp.add_tool` takes effect immediately and `send_tool_list_changed` reaches the client."""
    messages: list[object] = []

    async def collect(message: object) -> None:
        messages.append(message)

    async with Client(tutorial003.mcp, mode="legacy", message_handler=collect) as client:
        assert [tool.name for tool in (await client.list_tools()).tools] == ["enable_recommendations"]

        missing = await client.call_tool("recommend_book", {"genre": "fiction"})
        assert missing.is_error
        assert missing.content == [TextContent(type="text", text="Unknown tool: recommend_book")]

        enabled = await client.call_tool("enable_recommendations", {})
        assert enabled.content == [TextContent(type="text", text="Recommendations are now available.")]

        assert [tool.name for tool in (await client.list_tools()).tools] == [
            "enable_recommendations",
            "recommend_book",
        ]
        result = await client.call_tool("recommend_book", {"genre": "fiction"})
        assert result.content == [TextContent(type="text", text="In fiction, try 'Dune'.")]

    (notification,) = messages
    assert isinstance(notification, ToolListChangedNotification)
