"""`docs/tutorial/lifespan.md`: every claim the page makes, proved against the real SDK."""

import pytest
from inline_snapshot import snapshot
from mcp_types import TextContent, TextResourceContents

from docs_src.lifespan import tutorial001, tutorial002
from mcp import Client, MCPError
from mcp.server import MCPServer
from mcp.server.mcpserver import Context

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_lifespan_object_reaches_the_tool() -> None:
    """tutorial001: the object the lifespan yields is `ctx.request_context.lifespan_context`."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("count_books", {"genre": "poetry"})
        assert not result.is_error
        assert result.content == [TextContent(type="text", text="3 books in 'poetry'.")]
        assert result.structured_content == {"result": "3 books in 'poetry'."}


async def test_context_parameter_never_reaches_the_input_schema() -> None:
    async with Client(tutorial001.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.input_schema == snapshot(
            {
                "type": "object",
                "properties": {"genre": {"title": "Genre", "type": "string"}},
                "required": ["genre"],
                "title": "count_booksArguments",
            }
        )


async def test_startup_runs_before_the_first_request_and_shutdown_after_the_last() -> None:
    assert not tutorial002.database.connected
    async with Client(tutorial002.mcp) as client:
        assert tutorial002.database.connected
        result = await client.call_tool("database_status", {})
        assert result.structured_content == {"result": "connected"}
    assert not tutorial002.database.connected


async def test_bare_context_reaches_the_lifespan_object_in_resources_and_prompts() -> None:
    mcp = MCPServer("Bookshop", lifespan=tutorial001.app_lifespan)

    @mcp.resource("books://{genre}/count")
    def genre_count(genre: str, ctx: Context) -> str:
        """Count the books in a genre."""
        app = ctx.request_context.lifespan_context
        assert isinstance(app, tutorial001.AppContext)
        return f"{app.db.query()} books in {genre!r}."

    @mcp.prompt()
    def stock_report(ctx: Context) -> str:
        """Ask for a stock report."""
        app = ctx.request_context.lifespan_context
        assert isinstance(app, tutorial001.AppContext)
        return f"Summarise a shelf of {app.db.query()} books."

    async with Client(mcp) as client:
        resource = await client.read_resource("books://poetry/count")
        assert resource.contents == [
            TextResourceContents(uri="books://poetry/count", mime_type="text/plain", text="3 books in 'poetry'.")
        ]
        prompt = await client.get_prompt("stock_report")
        (message,) = prompt.messages
        assert message.content == TextContent(type="text", text="Summarise a shelf of 3 books.")


async def test_parameterized_context_is_tool_only(caplog: pytest.LogCaptureFixture) -> None:
    """`Context[AppContext]` on a resource or prompt fails every call; the server logs the `ValueError`."""
    mcp = MCPServer("Bookshop", lifespan=tutorial001.app_lifespan)

    @mcp.resource("books://{genre}/count")
    def genre_count(genre: str, ctx: Context[tutorial001.AppContext]) -> str:
        """Count the books in a genre."""
        return f"{ctx.request_context.lifespan_context.db.query()} books in {genre!r}."

    @mcp.prompt()
    def stock_report(ctx: Context[tutorial001.AppContext]) -> str:
        """Ask for a stock report."""
        return f"Summarise a shelf of {ctx.request_context.lifespan_context.db.query()} books."

    async with Client(mcp) as client:
        with pytest.raises(MCPError, match="Error creating resource from template"):
            await client.read_resource("books://poetry/count")
        assert "ValueError: Context is not available outside of a request" in caplog.text

        caplog.clear()
        with pytest.raises(MCPError):
            await client.get_prompt("stock_report")
        assert "ValueError: Context is not available outside of a request" in caplog.text


async def test_default_lifespan_yields_an_empty_dict() -> None:
    bare = MCPServer("Bare")

    @bare.tool()
    def show(ctx: Context) -> str:
        """Show the lifespan context."""
        return repr(ctx.request_context.lifespan_context)

    async with Client(bare) as client:
        result = await client.call_tool("show", {})
        assert result.structured_content == {"result": "{}"}
