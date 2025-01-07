import pytest

from mcp import types
from mcp.server.fastmcp import FastMCP


@pytest.mark.anyio
async def test_resource_templates():
    # Create an MCP server
    mcp = FastMCP("Demo")

    # Add a dynamic greeting resource
    @mcp.resource("greeting://{name}")
    def get_greeting(name: str) -> str:
        """Get a personalized greeting"""
        return f"Hello, {name}!"

    @mcp.resource("users://{user_id}/profile")
    def get_user_profile(user_id: str) -> str:
        """Dynamic user data"""
        return f"Profile data for user {user_id}"

    # Get the list of resource templates using the underlying server
    # Note: list_resource_templates() returns a decorator that wraps the handler
    # The handler returns a ServerResult with a ListResourceTemplatesResult inside
    result = await mcp._mcp_server.request_handlers[types.ListResourceTemplatesRequest](
        types.ListResourceTemplatesRequest(
            method="resources/templates/list", params=None, cursor=None
        )
    )
    assert isinstance(result.root, types.ListResourceTemplatesResult)
    templates = result.root.resourceTemplates

    # Verify we get both templates back
    assert len(templates) == 2

    # Verify template details
    greeting_template = next(t for t in templates if t.name == "get_greeting")
    assert greeting_template.uriTemplate == "greeting://{name}"
    assert greeting_template.description == "Get a personalized greeting"

    profile_template = next(t for t in templates if t.name == "get_user_profile")
    assert profile_template.uriTemplate == "users://{user_id}/profile"
    assert profile_template.description == "Dynamic user data"
