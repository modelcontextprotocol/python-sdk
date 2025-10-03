"""
Test for issue #671: create_connected_server_and_client_session API confusion

This issue was reported regarding confusion around the proper usage of the
create_connected_server_and_client_session function. The function signature
requires a server parameter, but developers were attempting to call it without
arguments or expecting it to return multiple values.

Common mistakes:
1. Calling without server parameter: create_connected_server_and_client_session()
2. Expecting tuple unpacking: server, client = create_connected_server_and_client_session(...)
"""

import pytest

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

pytestmark = pytest.mark.anyio


async def test_create_connected_server_and_client_session_requires_server():
    """
    Test that create_connected_server_and_client_session requires a server parameter.

    This reproduces the exact error from issue #671.
    """
    # This should raise TypeError for missing required positional argument
    with pytest.raises(TypeError, match="missing 1 required positional argument: 'server'"):
        async with create_connected_server_and_client_session():
            pass


async def test_create_connected_server_and_client_session_correct_usage():
    """
    Test the correct usage of create_connected_server_and_client_session.

    This demonstrates the proper way to use the function as documented.
    """
    # Create a test server
    server = FastMCP("TestServer")

    @server.tool()
    def test_tool(message: str = "Hello") -> str:
        """A test tool for validation."""
        return f"Response: {message}"

    @server.resource("test://example")
    def test_resource() -> str:
        """A test resource for validation."""
        return "Test resource content"

    # Correct usage: pass server and use as async context manager
    async with create_connected_server_and_client_session(server._mcp_server) as client_session:
        # Verify the session works
        assert client_session is not None

        # Test basic operations
        tools_result = await client_session.list_tools()
        assert len(tools_result.tools) == 1
        assert tools_result.tools[0].name == "test_tool"

        resources_result = await client_session.list_resources()
        assert len(resources_result.resources) == 1
        assert str(resources_result.resources[0].uri) == "test://example"

        # Test tool execution
        call_result = await client_session.call_tool("test_tool", {"message": "Issue 671 fixed"})
        assert call_result.content
        assert "Response: Issue 671 fixed" in call_result.content[0].text


async def test_create_connected_server_and_client_session_yields_single_value():
    """
    Test that the function yields a single ClientSession, not multiple values.

    This demonstrates the correct usage pattern - the function yields a single
    ClientSession object, not multiple values that can be unpacked.
    """
    server = FastMCP("SingleValueTestServer")

    @server.tool()
    def simple_tool() -> str:
        return "test"

    # Correct usage yields single ClientSession
    async with create_connected_server_and_client_session(server._mcp_server) as client_session:
        # Verify it's a single ClientSession object
        assert hasattr(client_session, 'call_tool')
        assert hasattr(client_session, 'list_tools')
        assert hasattr(client_session, 'list_resources')

        # Additional verification that it works as expected
        tools_result = await client_session.list_tools()
        assert len(tools_result.tools) == 1
        assert tools_result.tools[0].name == "simple_tool"