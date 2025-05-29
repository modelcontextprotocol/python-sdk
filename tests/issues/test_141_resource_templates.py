import json

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

    # Test case 2: Template with valid optional parameters
    # using form-style query expansion
    @mcp.resource("resource://users/{user_id}/profile{?format,fields}")
    def get_user_profile(
        user_id: str, format: str = "json", fields: str = "basic"
    ) -> str:
        return f"Profile for user {user_id} in {format} format with fields: {fields}"

    # Test case 3: Template with mismatched parameters
    with pytest.raises(
        ValueError,
        match="Mismatch between URI path parameters .* and "
        "required function parameters .*",
    ):

        @mcp.resource("resource://users/{user_id}/profile")
        def get_user_profile_mismatch(different_param: str) -> str:
            return f"Profile for user {different_param}"

    # Test case 4: Template with extra required function parameters
    with pytest.raises(
        ValueError,
        match="Mismatch between URI path parameters .* and "
        "required function parameters .*",
    ):

        @mcp.resource("resource://users/{user_id}/profile")
        def get_user_profile_extra(user_id: str, extra_param: str) -> str:
            return f"Profile for user {user_id}"

    # Test case 5: Template with missing function parameters
    with pytest.raises(
        ValueError,
        match="Mismatch between URI path parameters .* and "
        "required function parameters .*",
    ):

        @mcp.resource("resource://users/{user_id}/profile/{section}")
        def get_user_profile_missing(user_id: str) -> str:
            return f"Profile for user {user_id}"

    # Test case 6: Invalid query parameter in template (not optional in function)
    with pytest.raises(
        ValueError,
        match="Mismatch between URI path parameters .* and "
        "required function parameters .*",
    ):

        @mcp.resource("resource://users/{user_id}/profile{?required_param}")
        def get_user_profile_invalid_query(user_id: str, required_param: str) -> str:
            return f"Profile for user {user_id}"

    # Test case 7: Make sure the resource with form-style query parameters works
    async with client_session(mcp._mcp_server) as client:
        result = await client.read_resource(AnyUrl("resource://users/123/profile"))
        assert isinstance(result.contents[0], TextResourceContents)
        assert (
            result.contents[0].text
            == "Profile for user 123 in json format with fields: basic"
        )

        result = await client.read_resource(
            AnyUrl("resource://users/123/profile?format=xml")
        )
        assert isinstance(result.contents[0], TextResourceContents)
        assert (
            result.contents[0].text
            == "Profile for user 123 in xml format with fields: basic"
        )

        result = await client.read_resource(
            AnyUrl("resource://users/123/profile?format=xml&fields=detailed")
        )
        assert isinstance(result.contents[0], TextResourceContents)
        assert (
            result.contents[0].text
            == "Profile for user 123 in xml format with fields: detailed"
        )

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


@pytest.mark.anyio
async def test_resource_template_optional_param_default_fallback_e2e():
    """Test end-to-end that optional params fallback to defaults on validation error."""
    mcp = FastMCP("FallbackDemo")

    @mcp.resource("resource://config/{section}{?theme,timeout,is_feature_enabled}")
    def get_config(
        section: str,
        theme: str = "dark",
        timeout: int = 30,
        is_feature_enabled: bool = False,
    ) -> dict:
        return {
            "section": section,
            "theme": theme,
            "timeout": timeout,
            "is_feature_enabled": is_feature_enabled,
        }

    async with client_session(mcp._mcp_server) as client:
        await client.initialize()

        # 1. All defaults for optional params
        uri1 = "resource://config/network"
        res1 = await client.read_resource(AnyUrl(uri1))
        assert res1.contents and isinstance(res1.contents[0], TextResourceContents)
        data1 = json.loads(res1.contents[0].text)
        assert data1 == {
            "section": "network",
            "theme": "dark",
            "timeout": 30,
            "is_feature_enabled": False,
        }

        # 2. Valid optional params (theme is URL encoded, timeout is valid int string)
        uri2 = (
            "resource://config/ui?theme=light%20blue&timeout=60&is_feature_enabled=true"
        )
        res2 = await client.read_resource(AnyUrl(uri2))
        assert res2.contents and isinstance(res2.contents[0], TextResourceContents)
        data2 = json.loads(res2.contents[0].text)
        assert data2 == {
            "section": "ui",
            "theme": "light blue",
            "timeout": 60,
            "is_feature_enabled": True,
        }

        # 3.Invalid 'timeout'(optional int),valid 'theme','is_feature_enabled' not given
        # timeout=abc should use default 30
        uri3 = "resource://config/storage?theme=grayscale&timeout=abc"
        res3 = await client.read_resource(AnyUrl(uri3))
        assert res3.contents and isinstance(res3.contents[0], TextResourceContents)
        data3 = json.loads(res3.contents[0].text)
        assert data3 == {
            "section": "storage",
            "theme": "grayscale",
            "timeout": 30,  # Fallback to default
            "is_feature_enabled": False,  # Fallback to default
        }

        # 4.Invalid 'is_feature_enabled'(optional bool),'timeout'valid,'theme' not given
        # is_feature_enabled=notbool should use default False
        uri4 = "resource://config/user?timeout=15&is_feature_enabled=notbool"
        res4 = await client.read_resource(AnyUrl(uri4))
        assert res4.contents and isinstance(res4.contents[0], TextResourceContents)
        data4 = json.loads(res4.contents[0].text)
        assert data4 == {
            "section": "user",
            "theme": "dark",  # Fallback to default
            "timeout": 15,
            "is_feature_enabled": False,  # Fallback to default
        }

        # 5. Empty value for optional 'theme' (string type)
        uri5 = "resource://config/general?theme="
        res5 = await client.read_resource(AnyUrl(uri5))
        assert res5.contents and isinstance(res5.contents[0], TextResourceContents)
        data5 = json.loads(res5.contents[0].text)
        assert data5 == {
            "section": "general",
            "theme": "dark",  # Fallback to default because param is removed by parse_qs
            "timeout": 30,
            "is_feature_enabled": False,
        }

        # 6. Empty value for optional 'timeout' (int type)
        # timeout= (empty value) should fall back to default
        uri6 = "resource://config/advanced?timeout="
        res6 = await client.read_resource(AnyUrl(uri6))
        assert res6.contents and isinstance(res6.contents[0], TextResourceContents)
        data6 = json.loads(res6.contents[0].text)
        assert data6 == {
            "section": "advanced",
            "theme": "dark",
            "timeout": 30,  # Fallback to default because param is removed by parse_qs
            "is_feature_enabled": False,
        }

        # 7. Invalid required path param type
        # This scenario is more about the FastMCP.read_resource and its error handling
        @mcp.resource("resource://item/{item_code}/check")  # item_code is string here
        def check_item(item_code: int) -> dict:  # but int in function
            return {"item_code_type": str(type(item_code)), "valid_code": item_code > 0}

        uri7 = "resource://item/notaninteger/check"
        with pytest.raises(Exception, match="Error creating resource from template"):
            # The err is caught by FastMCP.read_resource and re-raised as ResourceError,
            # which the client sees as a general McpError or similar.
            await client.read_resource(AnyUrl(uri7))
