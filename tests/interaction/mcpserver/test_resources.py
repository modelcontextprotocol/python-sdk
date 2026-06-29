"""Resource interactions against MCPServer, driven through the public Client API."""

import pytest
from inline_snapshot import snapshot
from mcp_types import (
    ErrorData,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    TextResourceContents,
)

from mcp import MCPError
from mcp.server.mcpserver import MCPServer
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("mcpserver:resource:static")
async def test_read_static_resource(connect: Connect) -> None:
    mcp = MCPServer("library")

    @mcp.resource("config://app")
    def app_config() -> str:
        """The application configuration."""
        return "theme = dark"

    async with connect(mcp) as client:
        result = await client.read_resource("config://app")

    assert result == snapshot(
        ReadResourceResult(
            contents=[TextResourceContents(uri="config://app", mime_type="text/plain", text="theme = dark")]
        )
    )


@requirement("mcpserver:resource:static")
async def test_list_static_and_templated_resources(connect: Connect) -> None:
    """Static resources appear only in resources/list; templated ones only in templates/list."""
    mcp = MCPServer("library")

    @mcp.resource("config://app")
    def app_config() -> str:
        """The application configuration."""
        raise NotImplementedError  # registered for listing only; never read

    @mcp.resource("users://{user_id}/profile")
    def user_profile(user_id: str) -> str:
        """A user's profile."""
        raise NotImplementedError  # registered for listing only; never read

    async with connect(mcp) as client:
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
async def test_read_templated_resource(connect: Connect) -> None:
    mcp = MCPServer("library")

    @mcp.resource("users://{user_id}/profile")
    def user_profile(user_id: str) -> str:
        """A user's profile."""
        return f"profile for {user_id}"

    async with connect(mcp) as client:
        result = await client.read_resource("users://42/profile")

    assert result == snapshot(
        ReadResourceResult(
            contents=[TextResourceContents(uri="users://42/profile", mime_type="text/plain", text="profile for 42")]
        )
    )


@requirement("mcpserver:resource:unknown-uri")
async def test_read_unknown_uri_is_error(connect: Connect) -> None:
    """Reading a URI that matches no registered resource fails with -32602 and the URI in data (SEP-2164)."""
    mcp = MCPServer("library")

    @mcp.resource("config://app")
    def app_config() -> str:
        """A registered resource; the test reads a different URI."""
        raise NotImplementedError

    async with connect(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("config://missing")

    assert exc_info.value.error == snapshot(
        ErrorData(code=-32602, message="Unknown resource: config://missing", data={"uri": "config://missing"})
    )


@requirement("mcpserver:resource:read-throws-surfaced")
async def test_resource_function_that_raises_is_surfaced_as_a_jsonrpc_error(connect: Connect) -> None:
    """The -32603 error names only the URI; the original exception text is deliberately not leaked."""
    mcp = MCPServer("library")

    @mcp.resource("res://boom")
    def boom() -> str:
        raise RuntimeError("nope")

    async with connect(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("res://boom")

    assert exc_info.value.error == snapshot(
        ErrorData(code=-32603, message="Error reading resource res://boom", data={"uri": "res://boom"})
    )


@requirement("mcpserver:resource:duplicate-name")
async def test_registering_a_duplicate_resource_uri_warns_and_keeps_the_first(connect: Connect) -> None:
    """Intended behaviour is rejection at registration time (see the divergence note on the requirement)."""
    mcp = MCPServer("library")

    @mcp.resource("config://app")
    def config_first() -> str:
        """The first registration; this is the one that wins."""
        return "first"

    @mcp.resource("config://app")
    def config_second() -> str:
        """Registered at a duplicate URI; the registration is discarded so this never runs."""
        raise NotImplementedError

    async with connect(mcp) as client:
        listed = await client.list_resources()
        result = await client.read_resource("config://app")

    assert [resource.uri for resource in listed.resources] == ["config://app"]
    assert listed.resources[0].name == "config_first"
    assert result == snapshot(
        ReadResourceResult(contents=[TextResourceContents(uri="config://app", mime_type="text/plain", text="first")])
    )
