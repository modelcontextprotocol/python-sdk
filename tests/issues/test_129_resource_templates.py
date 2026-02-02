import pytest

from mcp import Client, types
from mcp.server.mcpserver import MCPServer


@pytest.mark.anyio
async def test_resource_templates():
    # Create an MCP server
    mcp = MCPServer("Demo")

    # Add a dynamic greeting resource
    @mcp.resource("greeting://{name}")
    def get_greeting(name: str) -> str:  # pragma: no cover
        """Get a personalized greeting"""
        return f"Hello, {name}!"

    @mcp.resource("users://{user_id}/profile")
    def get_user_profile(user_id: str) -> str:  # pragma: no cover
        """Dynamic user data"""
        return f"Profile data for user {user_id}"

    # Get the list of resource templates using the Client
    async with Client(mcp) as client:
        result = await client.list_resource_templates()
        templates = result.resource_templates

        # Verify we get both templates back
        assert len(templates) == 2

        # Verify template details
        greeting_template = next(t for t in templates if t.name == "get_greeting")
        assert greeting_template.uri_template == "greeting://{name}"
        assert greeting_template.description == "Get a personalized greeting"

        profile_template = next(t for t in templates if t.name == "get_user_profile")
        assert profile_template.uri_template == "users://{user_id}/profile"
        assert profile_template.description == "Dynamic user data"
