import pytest
from pydantic import FileUrl

from mcp import Client
from mcp.client.session import ClientSession
from mcp.server.mcpserver import Context, MCPServer
from mcp.shared._context import RequestContext
from mcp.types import ListRootsResult, Root, TextContent


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
        context: RequestContext[ClientSession],
    ) -> ListRootsResult:
        return callback_return

    @server.tool("test_list_roots")
    async def test_list_roots(context: Context, message: str):
        roots = await context.session.list_roots()
        assert roots == callback_return
        return True

    # Test with list_roots callback
    async with Client(server, list_roots_callback=list_roots_callback) as client:
        # Make a request to trigger sampling callback
        result = await client.call_tool("test_list_roots", {"message": "test message"})
        assert result.is_error is False
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "true"

    # Test without list_roots callback
    async with Client(server) as client:
        # Make a request to trigger sampling callback
        result = await client.call_tool("test_list_roots", {"message": "test message"})
        assert result.is_error is True
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Error executing tool test_list_roots: List roots not supported"


@pytest.mark.anyio
async def test_set_list_roots_callback():
    server = MCPServer("test")

    updated_result = ListRootsResult(
        roots=[
            Root(uri=FileUrl("file://users/fake/updated"), name="Updated Root"),
        ]
    )

    async def updated_callback(
        context: RequestContext[ClientSession],
    ) -> ListRootsResult:
        return updated_result

    @server.tool("get_roots")
    async def get_roots(context: Context, param: str) -> bool:
        roots = await context.session.list_roots()
        assert roots == updated_result
        return True

    async with Client(server) as client:
        # Before setting callback — default rejects with error
        result = await client.call_tool("get_roots", {"param": "x"})
        assert result.is_error is True

        # Set new callback — should succeed
        client.session.set_list_roots_callback(updated_callback)
        result = await client.call_tool("get_roots", {"param": "x"})
        assert result.is_error is False
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "true"

        # Reset to None — back to default error
        client.session.set_list_roots_callback(None)
        result = await client.call_tool("get_roots", {"param": "x"})
        assert result.is_error is True
