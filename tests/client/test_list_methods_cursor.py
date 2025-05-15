import pytest

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import (
    create_connected_server_and_client_session as create_session,
)

# Mark the whole module for async tests
pytestmark = pytest.mark.anyio


async def test_list_tools_cursor_parameter():
    """Test that the cursor parameter is accepted for list_tools.

    Note: FastMCP doesn't currently implement pagination, so this test
    only verifies that the cursor parameter is accepted by the client.
    """
    server = FastMCP("test")

    # Create a couple of test tools
    @server.tool(name="test_tool_1")
    async def test_tool_1() -> str:
        """First test tool"""
        return "Result 1"

    @server.tool(name="test_tool_2")
    async def test_tool_2() -> str:
        """Second test tool"""
        return "Result 2"

    async with create_session(server._mcp_server) as client_session:
        # Test without cursor parameter (omitted)
        result1 = await client_session.list_tools()
        assert len(result1.tools) == 2

        # Test with cursor=None
        result2 = await client_session.list_tools(cursor=None)
        assert len(result2.tools) == 2

        # Test with cursor as string
        result3 = await client_session.list_tools(cursor="some_cursor_value")
        assert len(result3.tools) == 2

        # Test with empty string cursor
        result4 = await client_session.list_tools(cursor="")
        assert len(result4.tools) == 2


async def test_list_resources_cursor_parameter():
    """Test that the cursor parameter is accepted for list_resources.

    Note: FastMCP doesn't currently implement pagination, so this test
    only verifies that the cursor parameter is accepted by the client.
    """
    server = FastMCP("test")

    # Create a test resource
    @server.resource("resource://test/data")
    async def test_resource() -> str:
        """Test resource"""
        return "Test data"

    async with create_session(server._mcp_server) as client_session:
        # Test without cursor parameter (omitted)
        result1 = await client_session.list_resources()
        assert len(result1.resources) >= 1

        # Test with cursor=None
        result2 = await client_session.list_resources(cursor=None)
        assert len(result2.resources) >= 1

        # Test with cursor as string
        result3 = await client_session.list_resources(cursor="some_cursor")
        assert len(result3.resources) >= 1

        # Test with empty string cursor
        result4 = await client_session.list_resources(cursor="")
        assert len(result4.resources) >= 1


async def test_list_prompts_cursor_parameter():
    """Test that the cursor parameter is accepted for list_prompts.

    Note: FastMCP doesn't currently implement pagination, so this test
    only verifies that the cursor parameter is accepted by the client.
    """
    server = FastMCP("test")

    # Create a test prompt
    @server.prompt()
    async def test_prompt(name: str) -> str:
        """Test prompt"""
        return f"Hello, {name}!"

    async with create_session(server._mcp_server) as client_session:
        # Test without cursor parameter (omitted)
        result1 = await client_session.list_prompts()
        assert len(result1.prompts) >= 1

        # Test with cursor=None
        result2 = await client_session.list_prompts(cursor=None)
        assert len(result2.prompts) >= 1

        # Test with cursor as string
        result3 = await client_session.list_prompts(cursor="some_cursor")
        assert len(result3.prompts) >= 1

        # Test with empty string cursor
        result4 = await client_session.list_prompts(cursor="")
        assert len(result4.prompts) >= 1


async def test_list_resource_templates_cursor_parameter():
    """Test that the cursor parameter is accepted for list_resource_templates.

    Note: FastMCP doesn't currently implement pagination, so this test
    only verifies that the cursor parameter is accepted by the client.
    """
    server = FastMCP("test")

    # Create a test resource template
    @server.resource("resource://test/{name}")
    async def test_template(name: str) -> str:
        """Test resource template"""
        return f"Data for {name}"

    async with create_session(server._mcp_server) as client_session:
        # Test without cursor parameter (omitted)
        result1 = await client_session.list_resource_templates()
        assert len(result1.resourceTemplates) >= 1

        # Test with cursor=None
        result2 = await client_session.list_resource_templates(cursor=None)
        assert len(result2.resourceTemplates) >= 1

        # Test with cursor as string
        result3 = await client_session.list_resource_templates(cursor="some_cursor")
        assert len(result3.resourceTemplates) >= 1

        # Test with empty string cursor
        result4 = await client_session.list_resource_templates(cursor="")
        assert len(result4.resourceTemplates) >= 1
