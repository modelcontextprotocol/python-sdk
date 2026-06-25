import pytest
from pydantic import FileUrl

from mcp import Client
from mcp.client import ClientRequestContext
from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_REQUEST, ListRootsResult, Root, TextContent


@pytest.mark.anyio
async def test_list_roots_callback():
    server = MCPServer("test")

    callback_return = ListRootsResult(
        roots=[
            Root(uri=FileUrl("file://users/fake/test"), name="Test Root 1"),
            Root(uri=FileUrl("file://users/fake/test/2"), name="Test Root 2"),
        ]
    )

    async def list_roots_callback(
        context: ClientRequestContext,
    ) -> ListRootsResult:
        return callback_return

    @server.tool("test_list_roots")
    async def test_list_roots(context: Context, message: str):
        roots = await context.session.list_roots()  # pyright: ignore[reportDeprecated]
        assert roots == callback_return
        return True

    # Test with list_roots callback
    async with Client(server, list_roots_callback=list_roots_callback, mode="legacy") as client:
        # Make a request to trigger sampling callback
        result = await client.call_tool("test_list_roots", {"message": "test message"})
        assert result.is_error is False
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "true"

    # Without a list_roots callback the client responds with an MCPError, which the
    # tool body doesn't catch — the wrapper re-raises it as a top-level JSON-RPC
    # error rather than wrapping it as an isError result.
    async with Client(server, mode="legacy") as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("test_list_roots", {"message": "test message"})
    assert exc_info.value.error.code == INVALID_REQUEST
