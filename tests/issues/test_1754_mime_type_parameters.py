"""Issue #1754: MIME type validation rejected valid RFC 2045 parameters like `text/html;profile=mcp-app`."""

import pytest

from mcp import Client
from mcp.server.mcpserver import MCPServer

pytestmark = pytest.mark.anyio


async def test_mime_type_with_parameters():
    mcp = MCPServer("test")

    @mcp.resource("ui://widget", mime_type="text/html;profile=mcp-app")
    def widget() -> str:
        raise NotImplementedError()

    resources = await mcp.list_resources()
    assert len(resources) == 1
    assert resources[0].mime_type == "text/html;profile=mcp-app"


async def test_mime_type_with_parameters_and_space():
    mcp = MCPServer("test")

    @mcp.resource("data://json", mime_type="application/json; charset=utf-8")
    def data() -> str:
        raise NotImplementedError()

    resources = await mcp.list_resources()
    assert len(resources) == 1
    assert resources[0].mime_type == "application/json; charset=utf-8"


async def test_mime_type_with_multiple_parameters():
    mcp = MCPServer("test")

    @mcp.resource("data://multi", mime_type="text/plain; charset=utf-8; format=fixed")
    def data() -> str:
        raise NotImplementedError()

    resources = await mcp.list_resources()
    assert len(resources) == 1
    assert resources[0].mime_type == "text/plain; charset=utf-8; format=fixed"


async def test_mime_type_preserved_in_read_resource():
    mcp = MCPServer("test")

    @mcp.resource("ui://my-widget", mime_type="text/html;profile=mcp-app")
    def my_widget() -> str:
        return "<html><body>Hello MCP-UI</body></html>"

    async with Client(mcp) as client:
        result = await client.read_resource("ui://my-widget")
        assert len(result.contents) == 1
        assert result.contents[0].mime_type == "text/html;profile=mcp-app"
