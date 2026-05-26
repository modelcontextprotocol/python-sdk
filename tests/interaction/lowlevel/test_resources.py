"""Resource interactions against the low-level Server, driven through the public Client API."""

import base64

import pytest
from inline_snapshot import snapshot

from mcp import MCPError, types
from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    Annotations,
    BlobResourceContents,
    CallToolResult,
    EmptyResult,
    ErrorData,
    Icon,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    ResourceUpdatedNotification,
    ResourceUpdatedNotificationParams,
    TextContent,
    TextResourceContents,
)
from tests.interaction._helpers import IncomingMessage
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("resources:list:basic")
async def test_list_resources_returns_registered_resources() -> None:
    """Listed resources reach the client with their URIs, names, and optional descriptive fields intact."""

    async def list_resources(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourcesResult:
        return ListResourcesResult(
            resources=[
                Resource(uri="memo://minimal", name="minimal"),
                Resource(
                    uri="file:///project/README.md",
                    name="readme",
                    title="Project README",
                    description="The project's front page.",
                    mime_type="text/markdown",
                    size=1024,
                    annotations=Annotations(audience=["user", "assistant"], priority=0.8),
                    icons=[Icon(src="https://example.com/readme.png", mime_type="image/png", sizes=["48x48"])],
                ),
            ]
        )

    server = Server("library", on_list_resources=list_resources)

    async with Client(server) as client:
        result = await client.list_resources()

    assert result == snapshot(
        ListResourcesResult(
            resources=[
                Resource(uri="memo://minimal", name="minimal"),
                Resource(
                    uri="file:///project/README.md",
                    name="readme",
                    title="Project README",
                    description="The project's front page.",
                    mime_type="text/markdown",
                    size=1024,
                    annotations=Annotations(audience=["user", "assistant"], priority=0.8),
                    icons=[Icon(src="https://example.com/readme.png", mime_type="image/png", sizes=["48x48"])],
                ),
            ]
        )
    )


@requirement("resources:read:text")
async def test_read_resource_text() -> None:
    """Reading a text resource returns its contents with the URI, MIME type, and text supplied by the handler."""

    async def read_resource(ctx: ServerRequestContext, params: types.ReadResourceRequestParams) -> ReadResourceResult:
        return ReadResourceResult(
            contents=[TextResourceContents(uri=params.uri, mime_type="text/plain", text="Hello, world!")]
        )

    server = Server("library", on_read_resource=read_resource)

    async with Client(server) as client:
        result = await client.read_resource("file:///greeting.txt")

    assert result == snapshot(
        ReadResourceResult(
            contents=[TextResourceContents(uri="file:///greeting.txt", mime_type="text/plain", text="Hello, world!")]
        )
    )


@requirement("resources:read:binary")
async def test_read_resource_binary() -> None:
    """Reading a binary resource returns its contents base64-encoded in the blob field."""

    async def read_resource(ctx: ServerRequestContext, params: types.ReadResourceRequestParams) -> ReadResourceResult:
        return ReadResourceResult(
            contents=[
                BlobResourceContents(
                    uri=params.uri,
                    mime_type="image/png",
                    blob=base64.b64encode(b"\x89PNG").decode(),
                )
            ]
        )

    server = Server("library", on_read_resource=read_resource)

    async with Client(server) as client:
        result = await client.read_resource("file:///pixel.png")

    assert result == snapshot(
        ReadResourceResult(
            contents=[BlobResourceContents(uri="file:///pixel.png", mime_type="image/png", blob="iVBORw==")]
        )
    )


@requirement("resources:read:not-found")
async def test_read_resource_unknown_uri_is_protocol_error() -> None:
    """A handler that rejects an unrecognised URI with MCPError produces a JSON-RPC error.

    The spec reserves -32002 for resource-not-found; the code is the handler's choice and reaches
    the client verbatim.
    """

    async def read_resource(ctx: ServerRequestContext, params: types.ReadResourceRequestParams) -> ReadResourceResult:
        raise MCPError(code=-32002, message=f"Resource not found: {params.uri}")

    server = Server("library", on_read_resource=read_resource)

    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("file:///missing.txt")

    assert exc_info.value.error == snapshot(ErrorData(code=-32002, message="Resource not found: file:///missing.txt"))


@requirement("resources:templates:list")
async def test_list_resource_templates_returns_registered_templates() -> None:
    """Listed resource templates reach the client with their URI templates and descriptive fields intact."""

    async def list_resource_templates(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourceTemplatesResult:
        return ListResourceTemplatesResult(
            resource_templates=[
                ResourceTemplate(uri_template="users://{user_id}", name="user"),
                ResourceTemplate(
                    uri_template="logs://{service}/{date}",
                    name="service_logs",
                    title="Service logs",
                    description="One day of logs for one service.",
                    mime_type="text/plain",
                    icons=[Icon(src="https://example.com/logs.png", mime_type="image/png", sizes=["48x48"])],
                ),
            ]
        )

    server = Server("library", on_list_resource_templates=list_resource_templates)

    async with Client(server) as client:
        result = await client.list_resource_templates()

    assert result == snapshot(
        ListResourceTemplatesResult(
            resource_templates=[
                ResourceTemplate(uri_template="users://{user_id}", name="user"),
                ResourceTemplate(
                    uri_template="logs://{service}/{date}",
                    name="service_logs",
                    title="Service logs",
                    description="One day of logs for one service.",
                    mime_type="text/plain",
                    icons=[Icon(src="https://example.com/logs.png", mime_type="image/png", sizes=["48x48"])],
                ),
            ]
        )
    )


@requirement("resources:subscribe")
async def test_subscribe_resource_delivers_uri_to_handler() -> None:
    """Subscribing to a resource delivers the URI to the server's subscribe handler and returns an empty result."""

    async def subscribe_resource(ctx: ServerRequestContext, params: types.SubscribeRequestParams) -> EmptyResult:
        assert params.uri == "file:///watched.txt"
        return EmptyResult()

    server = Server("library", on_subscribe_resource=subscribe_resource)

    async with Client(server) as client:
        result = await client.subscribe_resource("file:///watched.txt")

    assert result == snapshot(EmptyResult())


@requirement("resources:unsubscribe")
async def test_unsubscribe_resource_delivers_uri_to_handler() -> None:
    """Unsubscribing from a resource delivers the URI to the server's unsubscribe handler."""

    async def unsubscribe_resource(ctx: ServerRequestContext, params: types.UnsubscribeRequestParams) -> EmptyResult:
        assert params.uri == "file:///watched.txt"
        return EmptyResult()

    server = Server("library", on_unsubscribe_resource=unsubscribe_resource)

    async with Client(server) as client:
        result = await client.unsubscribe_resource("file:///watched.txt")

    assert result == snapshot(EmptyResult())


@requirement("resources:updated-notification")
async def test_resource_updated_notification_reaches_client() -> None:
    """A resources/updated notification sent during a tool call reaches the client with the resource URI.

    The collector records every message the handler receives, so the assertion also proves nothing
    else was delivered.
    """
    received: list[IncomingMessage] = []

    async def collect(message: IncomingMessage) -> None:
        received.append(message)

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="touch", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "touch"
        await ctx.session.send_resource_updated("file:///watched.txt")
        return CallToolResult(content=[TextContent(text="touched")])

    server = Server("library", on_list_tools=list_tools, on_call_tool=call_tool)

    async with Client(server, message_handler=collect) as client:
        await client.call_tool("touch", {})

    assert received == snapshot(
        [ResourceUpdatedNotification(params=ResourceUpdatedNotificationParams(uri="file:///watched.txt"))]
    )
