"""Resource interactions against MCPServer, driven through the public Client API."""

import pytest
from inline_snapshot import snapshot

from mcp import MCPError
from mcp.server.mcpserver import MCPServer
from mcp.types import (
    RESOURCE_NOT_FOUND,
    ErrorData,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    TextResourceContents,
)
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("mcpserver:resource:static")
async def test_read_static_resource(connect: Connect) -> None:
    """A function registered for a fixed URI is served at that URI with its return value as text."""
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
    """Reading a URI that matches a registered template invokes the function with the extracted parameters."""
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
    """Reading a URI that matches no registered resource fails with a JSON-RPC error.

    The spec reserves -32002 for resource-not-found.
    """
    mcp = MCPServer("library")

    @mcp.resource("config://app")
    def app_config() -> str:
        """A registered resource; the test reads a different URI."""
        raise NotImplementedError

    async with connect(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("config://missing")

    assert exc_info.value.error == snapshot(
        ErrorData(code=RESOURCE_NOT_FOUND, message="Unknown resource: config://missing")
    )


@requirement("mcpserver:resource:read-throws-surfaced")
async def test_resource_function_that_raises_is_surfaced_as_a_jsonrpc_error(connect: Connect) -> None:
    """An exception raised by a resource function reaches the caller as a JSON-RPC error.

    MCPServer wraps the failure in a generic error that names only the URI, so the original
    exception text is not leaked to the client. The wrapped exception becomes error code 0 the
    same way every other unhandled server-side exception does.
    """
    mcp = MCPServer("library")

    @mcp.resource("res://boom")
    def boom() -> str:
        raise RuntimeError("nope")

    async with connect(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("res://boom")

    assert exc_info.value.error == snapshot(ErrorData(code=0, message="Error reading resource res://boom"))


@requirement("mcpserver:resource:duplicate-name")
async def test_registering_a_duplicate_resource_uri_warns_and_keeps_the_first(connect: Connect) -> None:
    """Registering a second static resource at an already-used URI keeps the first registration.

    The intended behaviour is rejection at registration time; MCPServer instead logs a warning
    and discards the second registration (see the divergence note on the requirement). The two
    registrations use different function names so the test does not redefine a name in this scope;
    the resource decorator keys on the URI, not the function name.
    """
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
