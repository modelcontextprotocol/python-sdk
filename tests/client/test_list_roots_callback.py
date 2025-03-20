import pytest
from pydantic import FileUrl

from mcp.client.session import ClientSession
from mcp.server.fastmcp.server import Context
from mcp.shared.context import RequestContext
from mcp.shared.memory import (
    create_connected_server_and_client_session as create_session,
)
from mcp.types import ListRootsResult, Root, TextContent


@pytest.mark.anyio
async def test_list_roots_callback():
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("test")

    callback_return = ListRootsResult(
        roots=[
            Root(
                uri=FileUrl("file://users/fake/test"),
                name="Test Root 1",
            ),
            Root(
                uri=FileUrl("file://users/fake/test/2"),
                name="Test Root 2",
            ),
        ]
    )

    async def list_roots_callback(
        context: RequestContext[ClientSession, None],
    ) -> ListRootsResult:
        return callback_return

    @server.tool("test_list_roots")
    async def test_list_roots(context: Context, message: str):  # type: ignore[reportUnknownMemberType]
        roots = await context.session.list_roots()
        assert roots == callback_return
        return True

    # Test with list_roots callback
    async with create_session(
        server._mcp_server, list_roots_callback=list_roots_callback
    ) as client_session:
        # Make a request to trigger sampling callback
        result = await client_session.call_tool(
            "test_list_roots", {"message": "test message"}
        )
        assert result.isError is False
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "true"

    # Test without list_roots callback
    async with create_session(server._mcp_server) as client_session:
        # Make a request to trigger sampling callback
        result = await client_session.call_tool(
            "test_list_roots", {"message": "test message"}
        )
        assert result.isError is True
        assert isinstance(result.content[0], TextContent)
        assert (
            result.content[0].text
            == "Error executing tool test_list_roots: List roots not supported"
        )
