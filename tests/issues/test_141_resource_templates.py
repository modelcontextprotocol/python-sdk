import pytest
from pydantic import AnyUrl

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import (
    create_connected_server_and_client_session as client_session,
)
from mcp.types import (
    ListResourceTemplatesResult,
    TextResourceContents,
)


@pytest.mark.anyio
async def test_resource_template_edge_cases():
    """Test server-side resource template validation"""
    mcp = FastMCP("Demo")

    # Test case 1: Template with multiple parameters
    @mcp.resource("resource://users/{user_id}/posts/{post_id}")
    def get_user_post(user_id: str, post_id: str) -> str:
        return f"Post {post_id} by user {user_id}"

    # Test case 2: Template with optional parameter (should fail)
    with pytest.raises(ValueError, match="Mismatch between URI parameters"):

        @mcp.resource("resource://users/{user_id}/profile")
        def get_user_profile(user_id: str, optional_param: str | None = None) -> str:
            return f"Profile for user {user_id}"

    # Test case 3: Template with mismatched parameters
    with pytest.raises(ValueError, match="Mismatch between URI parameters"):

        @mcp.resource("resource://users/{user_id}/profile")
        def get_user_profile_mismatch(different_param: str) -> str:
            return f"Profile for user {different_param}"

    # Test case 4: Template with extra function parameters
    with pytest.raises(ValueError, match="Mismatch between URI parameters"):

        @mcp.resource("resource://users/{user_id}/profile")
        def get_user_profile_extra(user_id: str, extra_param: str) -> str:
            return f"Profile for user {user_id}"

    # Test case 5: Template with missing function parameters
    with pytest.raises(ValueError, match="Mismatch between URI parameters"):

        @mcp.resource("resource://users/{user_id}/profile/{section}")
        def get_user_profile_missing(user_id: str) -> str:
            return f"Profile for user {user_id}"

    # Verify valid template works
    result = await mcp.read_resource("resource://users/123/posts/456")
    result_list = list(result)
    assert len(result_list) == 1
    assert result_list[0].content == "Post 456 by user 123"
    assert result_list[0].mime_type == "text/plain"

    # Verify invalid parameters raise error
    with pytest.raises(ValueError, match="Unknown resource"):
        await mcp.read_resource("resource://users/123/posts")  # Missing post_id

    with pytest.raises(ValueError, match="Unknown resource"):
        await mcp.read_resource(
            "resource://users/123/posts/456/extra"
        )  # Extra path component


@pytest.mark.anyio
async def test_resource_template_client_interaction():
    """Test client-side resource template interaction"""
    mcp = FastMCP("Demo")

    # Register some templated resources
    @mcp.resource("resource://users/{user_id}/posts/{post_id}")
    def get_user_post(user_id: str, post_id: str) -> str:
        return f"Post {post_id} by user {user_id}"

    @mcp.resource("resource://users/{user_id}/profile")
    def get_user_profile(user_id: str) -> str:
        return f"Profile for user {user_id}"

    async with client_session(mcp._mcp_server) as session:
        # Initialize the session
        await session.initialize()

        # List available resources
        resources = await session.list_resource_templates()
        assert isinstance(resources, ListResourceTemplatesResult)
        assert len(resources.resourceTemplates) == 2

        # Verify resource templates are listed correctly
        templates = [r.uriTemplate for r in resources.resourceTemplates]
        assert "resource://users/{user_id}/posts/{post_id}" in templates
        assert "resource://users/{user_id}/profile" in templates

        # Read a resource with valid parameters
        result = await session.read_resource(AnyUrl("resource://users/123/posts/456"))
        contents = result.contents[0]
        assert isinstance(contents, TextResourceContents)
        assert contents.text == "Post 456 by user 123"
        assert contents.mimeType == "text/plain"

        # Read another resource with valid parameters
        result = await session.read_resource(AnyUrl("resource://users/789/profile"))
        contents = result.contents[0]
        assert isinstance(contents, TextResourceContents)
        assert contents.text == "Profile for user 789"
        assert contents.mimeType == "text/plain"

        # Verify invalid resource URIs raise appropriate errors
        with pytest.raises(Exception):  # Specific exception type may vary
            await session.read_resource(
                AnyUrl("resource://users/123/posts")
            )  # Missing post_id

        with pytest.raises(Exception):  # Specific exception type may vary
            await session.read_resource(
                AnyUrl("resource://users/123/invalid")
            )  # Invalid template
