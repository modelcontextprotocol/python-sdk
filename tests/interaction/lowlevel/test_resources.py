"""Resource interactions against the low-level Server, driven through the public Client API."""

import base64

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    METHOD_NOT_FOUND,
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

from mcp import MCPError
from mcp.server import Server, ServerRequestContext
from tests._stamp import unstamped
from tests.interaction._connect import Connect
from tests.interaction._helpers import IncomingMessage
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("resources:list:basic")
@requirement("resources:annotations")
async def test_list_resources_returns_registered_resources(connect: Connect) -> None:
    """Listed resources reach the client with their URIs, names, and optional descriptive fields intact.

    The fully-populated entry includes annotations, so the snapshot also proves they round-trip.
    The SDK's Annotations model omits the schema's lastModified field (see the divergence on
    resources:annotations); the input is built via model_validate with lastModified set so the
    snapshot pins the drop and will fail once the SDK adds the field.
    """

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
                    annotations=Annotations.model_validate(
                        {"audience": ["user", "assistant"], "priority": 0.8, "lastModified": "2025-01-01T00:00:00Z"}
                    ),
                    icons=[Icon(src="https://example.com/readme.png", mime_type="image/png", sizes=["48x48"])],
                ),
            ]
        )

    server = Server("library", on_list_resources=list_resources)

    async with connect(server) as client:
        result = await client.list_resources()

    assert unstamped(result) == snapshot(
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
                    annotations=Annotations(
                        audience=["user", "assistant"], priority=0.8, last_modified="2025-01-01T00:00:00Z"
                    ),
                    icons=[Icon(src="https://example.com/readme.png", mime_type="image/png", sizes=["48x48"])],
                ),
            ]
        )
    )


@requirement("resources:read:text")
async def test_read_resource_text(connect: Connect) -> None:
    """Reading a text resource returns its contents with the URI, MIME type, and text supplied by the handler."""

    async def read_resource(ctx: ServerRequestContext, params: types.ReadResourceRequestParams) -> ReadResourceResult:
        return ReadResourceResult(
            contents=[TextResourceContents(uri=params.uri, mime_type="text/plain", text="Hello, world!")]
        )

    server = Server("library", on_read_resource=read_resource)

    async with connect(server) as client:
        result = await client.read_resource("file:///greeting.txt")

    assert unstamped(result) == snapshot(
        ReadResourceResult(
            contents=[TextResourceContents(uri="file:///greeting.txt", mime_type="text/plain", text="Hello, world!")]
        )
    )


@requirement("resources:read:blob")
async def test_read_resource_binary(connect: Connect) -> None:
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

    async with connect(server) as client:
        result = await client.read_resource("file:///pixel.png")

    assert unstamped(result) == snapshot(
        ReadResourceResult(
            contents=[BlobResourceContents(uri="file:///pixel.png", mime_type="image/png", blob="iVBORw==")]
        )
    )


@requirement("resources:read:unknown-uri")
async def test_read_resource_unknown_uri_is_protocol_error(connect: Connect) -> None:
    """A handler that rejects an unrecognised URI with MCPError produces a JSON-RPC error.

    The spec reserves -32002 for resource-not-found; the code is the handler's choice and reaches
    the client verbatim.
    """

    async def read_resource(ctx: ServerRequestContext, params: types.ReadResourceRequestParams) -> ReadResourceResult:
        raise MCPError(code=-32002, message=f"Resource not found: {params.uri}")

    server = Server("library", on_read_resource=read_resource)

    async with connect(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("file:///missing.txt")

    assert exc_info.value.error == snapshot(ErrorData(code=-32002, message="Resource not found: file:///missing.txt"))


@requirement("resources:templates:list")
async def test_list_resource_templates_returns_registered_templates(connect: Connect) -> None:
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

    async with connect(server) as client:
        result = await client.list_resource_templates()

    assert unstamped(result) == snapshot(
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


@pytest.mark.filterwarnings("ignore::mcp.MCPDeprecationWarning")
@requirement("resources:subscribe")
async def test_subscribe_resource_delivers_uri_to_handler(connect: Connect) -> None:
    """Subscribing to a resource delivers the URI to the server's subscribe handler and returns an empty result."""

    async def subscribe_resource(ctx: ServerRequestContext, params: types.SubscribeRequestParams) -> EmptyResult:
        assert params.uri == "file:///watched.txt"
        return EmptyResult()

    server = Server("library", on_subscribe_resource=subscribe_resource)

    async with connect(server) as client:
        result = await client.subscribe_resource("file:///watched.txt")  # pyright: ignore[reportDeprecated]

    assert result == snapshot(EmptyResult())


@pytest.mark.filterwarnings("ignore::mcp.MCPDeprecationWarning")
@requirement("resources:subscribe:capability-required")
async def test_subscribe_without_a_subscribe_handler_is_method_not_found(connect: Connect) -> None:
    """Subscribing to a server that registered no subscribe handler is rejected with METHOD_NOT_FOUND.

    The rejection comes from no handler being registered, not from any capability check; see the
    divergence on lifecycle:capability:server-not-advertised.
    """

    async def list_resources(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourcesResult:
        """Registered only so the resources capability is advertised; never called."""
        raise NotImplementedError

    server = Server("library", on_list_resources=list_resources)

    async with connect(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.subscribe_resource("file:///watched.txt")  # pyright: ignore[reportDeprecated]

    assert exc_info.value.error == snapshot(
        ErrorData(code=METHOD_NOT_FOUND, message="Method not found", data="resources/subscribe")
    )


@pytest.mark.filterwarnings("ignore::mcp.MCPDeprecationWarning")
@requirement("resources:unsubscribe")
async def test_unsubscribe_resource_delivers_uri_to_handler(connect: Connect) -> None:
    """Unsubscribing from a resource delivers the URI to the server's unsubscribe handler."""

    async def unsubscribe_resource(ctx: ServerRequestContext, params: types.UnsubscribeRequestParams) -> EmptyResult:
        assert params.uri == "file:///watched.txt"
        return EmptyResult()

    server = Server("library", on_unsubscribe_resource=unsubscribe_resource)

    async with connect(server) as client:
        result = await client.unsubscribe_resource("file:///watched.txt")  # pyright: ignore[reportDeprecated]

    assert result == snapshot(EmptyResult())


@requirement("resources:updated-notification")
async def test_resource_updated_notification_reaches_client(connect: Connect) -> None:
    """A resources/updated notification sent during a tool call reaches the client with the resource URI.

    ``send_resource_updated`` does not take a ``related_request_id``, so over streamable HTTP the
    notification routes to the standalone GET stream and is not guaranteed to arrive before the
    tool result; the test waits on an event the collector sets. The collector records every
    message the handler receives, so the assertion also proves nothing else was delivered.
    """
    received: list[IncomingMessage] = []
    seen = anyio.Event()

    async def collect(message: IncomingMessage) -> None:
        received.append(message)
        seen.set()

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="touch", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "touch"
        await ctx.session.send_resource_updated("file:///watched.txt")
        return CallToolResult(content=[TextContent(text="touched")])

    async def list_resources(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourcesResult:
        """Registered so the resources capability is advertised; the client never lists resources."""
        raise NotImplementedError

    async def subscribe_resource(ctx: ServerRequestContext, params: types.SubscribeRequestParams) -> EmptyResult:
        """Registered so the resources subscribe sub-capability is advertised; the client never subscribes."""
        raise NotImplementedError

    server = Server(
        "library",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_list_resources=list_resources,
        on_subscribe_resource=subscribe_resource,
    )

    async with connect(server, message_handler=collect) as client:
        await client.call_tool("touch", {})
        with anyio.fail_after(5):
            await seen.wait()

    assert received == snapshot(
        [ResourceUpdatedNotification(params=ResourceUpdatedNotificationParams(uri="file:///watched.txt"))]
    )
