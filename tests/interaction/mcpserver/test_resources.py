"""Resource interactions against MCPServer, driven through the public Client API."""

import pytest
from inline_snapshot import snapshot

from mcp import MCPError
from mcp.client.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import (
    ErrorData,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    TextResourceContents,
)
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("mcpserver:resource:static")
async def test_read_static_resource() -> None:
    """A function registered for a fixed URI is served at that URI with its return value as text."""
    mcp = MCPServer("library")

    @mcp.resource("config://app")
    def app_config() -> str:
        """The application configuration."""
        return "theme = dark"

    async with Client(mcp) as client:
        result = await client.read_resource("config://app")

    assert result == snapshot(
        ReadResourceResult(
            contents=[TextResourceContents(uri="config://app", mime_type="text/plain", text="theme = dark")]
        )
    )


@requirement("mcpserver:resource:static")
async def test_list_static_and_templated_resources() -> None:
    """Statically-registered resources appear in resources/list; templated ones only in templates/list.

    The name and description are derived from the function name and docstring; the MIME type
    defaults to text/plain.
    """
    mcp = MCPServer("library")

    @mcp.resource("config://app")
    def app_config() -> str:
        """The application configuration."""
        raise NotImplementedError  # registered for listing only; never read

    @mcp.resource("users://{user_id}/profile")
    def user_profile(user_id: str) -> str:
        """A user's profile."""
        raise NotImplementedError  # registered for listing only; never read

    async with Client(mcp) as client:
        resources = await client.list_resources()
        templates = await client.list_resource_templates()

    assert resources == snapshot(
        ListResourcesResult(
            resources=[
                Resource(
                    name="app_config",
                    uri="config://app",
                    description="The application configuration.",
                    mime_type="text/plain",
                )
            ]
        )
    )
    assert templates == snapshot(
        ListResourceTemplatesResult(
            resource_templates=[
                ResourceTemplate(
                    name="user_profile",
                    uri_template="users://{user_id}/profile",
                    description="A user's profile.",
                    mime_type="text/plain",
                )
            ]
        )
    )


@requirement("mcpserver:resource:template")
@requirement("resources:read:template-vars")
async def test_read_templated_resource() -> None:
    """Reading a URI that matches a registered template invokes the function with the extracted parameters."""
    mcp = MCPServer("library")

    @mcp.resource("users://{user_id}/profile")
    def user_profile(user_id: str) -> str:
        """A user's profile."""
        return f"profile for {user_id}"

    async with Client(mcp) as client:
        result = await client.read_resource("users://42/profile")

    assert result == snapshot(
        ReadResourceResult(
            contents=[TextResourceContents(uri="users://42/profile", mime_type="text/plain", text="profile for 42")]
        )
    )


@requirement("mcpserver:resource:unknown-uri")
async def test_read_unknown_uri_is_error() -> None:
    """Reading a URI that matches no registered resource fails with a JSON-RPC error.

    The spec reserves -32002 for resource-not-found; see the divergence note on the requirement.
    """
    mcp = MCPServer("library")

    @mcp.resource("config://app")
    def app_config() -> str:
        """A registered resource; the test reads a different URI."""
        raise NotImplementedError

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("config://missing")

    assert exc_info.value.error == snapshot(ErrorData(code=0, message="Unknown resource: config://missing"))
