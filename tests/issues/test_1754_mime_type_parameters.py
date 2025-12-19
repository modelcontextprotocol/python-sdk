"""Test for GitHub issue #1754: MIME type validation rejects valid RFC 2045 parameters.

The MIME type validation regex was too restrictive and rejected valid MIME types
with parameters like 'text/html;profile=mcp-app' which are valid per RFC 2045.
"""

import pytest
from pydantic import AnyUrl

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import (
    create_connected_server_and_client_session as client_session,
)

pytestmark = pytest.mark.anyio


async def test_mime_type_with_parameters():
    """Test that MIME types with parameters are accepted (RFC 2045)."""
    mcp = FastMCP("test")

    # This should NOT raise a validation error
    @mcp.resource("ui://widget", mime_type="text/html;profile=mcp-app")
    def widget() -> str:
        raise NotImplementedError()

    resources = await mcp.list_resources()
    assert len(resources) == 1
    assert resources[0].mimeType == "text/html;profile=mcp-app"


async def test_mime_type_with_parameters_and_space():
    """Test MIME type with space after semicolon."""
    mcp = FastMCP("test")

    @mcp.resource("data://json", mime_type="application/json; charset=utf-8")
    def data() -> str:
        raise NotImplementedError()

    resources = await mcp.list_resources()
    assert len(resources) == 1
    assert resources[0].mimeType == "application/json; charset=utf-8"


async def test_mime_type_with_multiple_parameters():
    """Test MIME type with multiple parameters."""
    mcp = FastMCP("test")

    @mcp.resource("data://multi", mime_type="text/plain; charset=utf-8; format=fixed")
    def data() -> str:
        raise NotImplementedError()

    resources = await mcp.list_resources()
    assert len(resources) == 1
    assert resources[0].mimeType == "text/plain; charset=utf-8; format=fixed"


async def test_mime_type_preserved_in_read_resource():
    """Test that MIME type with parameters is preserved when reading resource."""
    mcp = FastMCP("test")

    @mcp.resource("ui://my-widget", mime_type="text/html;profile=mcp-app")
    def my_widget() -> str:
        return "<html><body>Hello MCP-UI</body></html>"

    async with client_session(mcp._mcp_server) as client:
        # Read the resource
        result = await client.read_resource(AnyUrl("ui://my-widget"))
        assert len(result.contents) == 1
        assert result.contents[0].mimeType == "text/html;profile=mcp-app"
