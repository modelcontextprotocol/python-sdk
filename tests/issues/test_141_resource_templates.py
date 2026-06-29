import pytest
from mcp_types import (
    ListResourceTemplatesResult,
    TextResourceContents,
)

from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError


@pytest.mark.anyio
async def test_resource_template_edge_cases():
    mcp = MCPServer("Demo")

    @mcp.resource("resource://users/{user_id}/posts/{post_id}")
    def get_user_post(user_id: str, post_id: str) -> str:
        return f"Post {post_id} by user {user_id}"

    with pytest.raises(ValueError, match="Mismatch between URI parameters"):

        @mcp.resource("resource://users/{user_id}/profile")
        def get_user_profile(user_id: str, optional_param: str | None = None) -> str:  # pragma: no cover
            return f"Profile for user {user_id}"

    with pytest.raises(ValueError, match="Mismatch between URI parameters"):

        @mcp.resource("resource://users/{user_id}/profile")
        def get_user_profile_mismatch(different_param: str) -> str:  # pragma: no cover
            return f"Profile for user {different_param}"

    with pytest.raises(ValueError, match="Mismatch between URI parameters"):

        @mcp.resource("resource://users/{user_id}/profile")
        def get_user_profile_extra(user_id: str, extra_param: str) -> str:  # pragma: no cover
            return f"Profile for user {user_id}"

    with pytest.raises(ValueError, match="Mismatch between URI parameters"):

        @mcp.resource("resource://users/{user_id}/profile/{section}")
        def get_user_profile_missing(user_id: str) -> str:  # pragma: no cover
            return f"Profile for user {user_id}"

    result = await mcp.read_resource("resource://users/123/posts/456")
    result_list = list(result)
    assert len(result_list) == 1
    assert result_list[0].content == "Post 456 by user 123"
    assert result_list[0].mime_type == "text/plain"

    with pytest.raises(ResourceError, match="Unknown resource"):
        await mcp.read_resource("resource://users/123/posts")  # Missing post_id

    with pytest.raises(ResourceError, match="Unknown resource"):
        await mcp.read_resource("resource://users/123/posts/456/extra")  # Extra path component


@pytest.mark.anyio
async def test_resource_template_client_interaction():
    mcp = MCPServer("Demo")

    @mcp.resource("resource://users/{user_id}/posts/{post_id}")
    def get_user_post(user_id: str, post_id: str) -> str:
        return f"Post {post_id} by user {user_id}"

    @mcp.resource("resource://users/{user_id}/profile")
    def get_user_profile(user_id: str) -> str:
        return f"Profile for user {user_id}"

    async with Client(mcp) as session:
        resources = await session.list_resource_templates()
        assert isinstance(resources, ListResourceTemplatesResult)
        assert len(resources.resource_templates) == 2

        templates = [r.uri_template for r in resources.resource_templates]
        assert "resource://users/{user_id}/posts/{post_id}" in templates
        assert "resource://users/{user_id}/profile" in templates

        result = await session.read_resource("resource://users/123/posts/456")
        contents = result.contents[0]
        assert isinstance(contents, TextResourceContents)
        assert contents.text == "Post 456 by user 123"
        assert contents.mime_type == "text/plain"

        result = await session.read_resource("resource://users/789/profile")
        contents = result.contents[0]
        assert isinstance(contents, TextResourceContents)
        assert contents.text == "Profile for user 789"
        assert contents.mime_type == "text/plain"

        with pytest.raises(Exception):  # Specific exception type may vary
            await session.read_resource("resource://users/123/posts")  # Missing post_id

        with pytest.raises(Exception):  # Specific exception type may vary
            await session.read_resource("resource://users/123/invalid")  # Invalid template
