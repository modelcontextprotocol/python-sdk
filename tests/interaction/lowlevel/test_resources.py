"""Resource interactions against the low-level Server, driven through the public Client API."""

from typing import Any

import anyio
import pytest
from inline_snapshot import snapshot
from pydantic import AnyUrl

from mcp import McpError, types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types import (
    METHOD_NOT_FOUND,
    Annotations,
    BlobResourceContents,
    EmptyResult,
    ErrorData,
    Icon,
    ListResourceTemplatesResult,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    ResourceUpdatedNotification,
    ResourceUpdatedNotificationParams,
    ServerNotification,
    TextContent,
    TextResourceContents,
)
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
    resources:annotations) but allows extra fields, so lastModified round-trips as an undeclared
    extra; the snapshot compares the serialised dict so the extra key is visible and pinned.
    """
    server = Server("library")

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        return [
            Resource(uri="memo://minimal", name="minimal"),
            Resource(
                uri="file:///project/README.md",
                name="readme",
                title="Project README",
                description="The project's front page.",
                mimeType="text/markdown",
                size=1024,
                annotations=Annotations.model_validate(
                    {"audience": ["user", "assistant"], "priority": 0.8, "lastModified": "2025-01-01T00:00:00Z"}
                ),
                icons=[Icon(src="https://example.com/readme.png", mimeType="image/png", sizes=["48x48"])],
            ),
        ]

    async with connect(server) as client:
        result = await client.list_resources()

    assert result.model_dump(by_alias=True, exclude_none=True) == snapshot(
        {
            "resources": [
                {"name": "minimal", "uri": AnyUrl("memo://minimal")},
                {
                    "name": "readme",
                    "title": "Project README",
                    "uri": AnyUrl("file:///project/README.md"),
                    "description": "The project's front page.",
                    "mimeType": "text/markdown",
                    "size": 1024,
                    "icons": [{"src": "https://example.com/readme.png", "mimeType": "image/png", "sizes": ["48x48"]}],
                    "annotations": {
                        "audience": ["user", "assistant"],
                        "priority": 0.8,
                        "lastModified": "2025-01-01T00:00:00Z",
                    },
                },
            ]
        }
    )


@requirement("resources:read:text")
async def test_read_resource_text(connect: Connect) -> None:
    """Reading a text resource returns its contents with the URI, MIME type, and text supplied by the handler."""
    server = Server("library")

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        return [ReadResourceContents(content="Hello, world!", mime_type="text/plain")]

    async with connect(server) as client:
        result = await client.read_resource(AnyUrl("file:///greeting.txt"))

    assert result == snapshot(
        ReadResourceResult(
            contents=[TextResourceContents(uri="file:///greeting.txt", mimeType="text/plain", text="Hello, world!")]
        )
    )


@requirement("resources:read:blob")
async def test_read_resource_binary(connect: Connect) -> None:
    """Reading a binary resource returns its contents base64-encoded in the blob field.

    The low-level decorator base64-encodes the bytes returned via ``ReadResourceContents``.
    """
    server = Server("library")

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        return [ReadResourceContents(content=b"\x89PNG", mime_type="image/png")]

    async with connect(server) as client:
        result = await client.read_resource(AnyUrl("file:///pixel.png"))

    assert result == snapshot(
        ReadResourceResult(
            contents=[BlobResourceContents(uri="file:///pixel.png", mimeType="image/png", blob="iVBORw==")]
        )
    )


@requirement("resources:read:unknown-uri")
async def test_read_resource_unknown_uri_is_protocol_error(connect: Connect) -> None:
    """A handler that rejects an unrecognised URI with McpError produces a JSON-RPC error.

    The spec reserves -32002 for resource-not-found; the code is the handler's choice and reaches
    the client verbatim.
    """
    server = Server("library")

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        raise McpError(ErrorData(code=-32002, message=f"Resource not found: {uri}"))

    async with connect(server) as client:
        with pytest.raises(McpError) as exc_info:
            await client.read_resource(AnyUrl("file:///missing.txt"))

    assert exc_info.value.error == snapshot(ErrorData(code=-32002, message="Resource not found: file:///missing.txt"))


@requirement("resources:templates:list")
async def test_list_resource_templates_returns_registered_templates(connect: Connect) -> None:
    """Listed resource templates reach the client with their URI templates and descriptive fields intact."""
    server = Server("library")

    @server.list_resource_templates()
    async def list_resource_templates() -> list[ResourceTemplate]:
        return [
            ResourceTemplate(uriTemplate="users://{user_id}", name="user"),
            ResourceTemplate(
                uriTemplate="logs://{service}/{date}",
                name="service_logs",
                title="Service logs",
                description="One day of logs for one service.",
                mimeType="text/plain",
                icons=[Icon(src="https://example.com/logs.png", mimeType="image/png", sizes=["48x48"])],
            ),
        ]

    async with connect(server) as client:
        result = await client.list_resource_templates()

    assert result == snapshot(
        ListResourceTemplatesResult(
            resourceTemplates=[
                ResourceTemplate(uriTemplate="users://{user_id}", name="user"),
                ResourceTemplate(
                    uriTemplate="logs://{service}/{date}",
                    name="service_logs",
                    title="Service logs",
                    description="One day of logs for one service.",
                    mimeType="text/plain",
                    icons=[Icon(src="https://example.com/logs.png", mimeType="image/png", sizes=["48x48"])],
                ),
            ]
        )
    )


@requirement("resources:subscribe")
async def test_subscribe_resource_delivers_uri_to_handler(connect: Connect) -> None:
    """Subscribing to a resource delivers the URI to the server's subscribe handler and returns an empty result."""
    server = Server("library")

    @server.subscribe_resource()
    async def subscribe_resource(uri: AnyUrl) -> None:
        assert uri == AnyUrl("file:///watched.txt")

    async with connect(server) as client:
        result = await client.subscribe_resource(AnyUrl("file:///watched.txt"))

    assert result == snapshot(EmptyResult())


@requirement("resources:subscribe:capability-required")
async def test_subscribe_without_a_subscribe_handler_is_method_not_found(connect: Connect) -> None:
    """Subscribing to a server that registered no subscribe handler is rejected with METHOD_NOT_FOUND.

    The rejection comes from no handler being registered, not from any capability check; see the
    divergence on lifecycle:capability:server-not-advertised.
    """

    server = Server("library")

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        """Registered only so the resources capability is advertised; never called."""
        raise NotImplementedError

    async with connect(server) as client:
        with pytest.raises(McpError) as exc_info:
            await client.subscribe_resource(AnyUrl("file:///watched.txt"))

    assert exc_info.value.error == snapshot(ErrorData(code=METHOD_NOT_FOUND, message="Method not found"))


@requirement("resources:unsubscribe")
async def test_unsubscribe_resource_delivers_uri_to_handler(connect: Connect) -> None:
    """Unsubscribing from a resource delivers the URI to the server's unsubscribe handler."""
    server = Server("library")

    @server.unsubscribe_resource()
    async def unsubscribe_resource(uri: AnyUrl) -> None:
        assert uri == AnyUrl("file:///watched.txt")

    async with connect(server) as client:
        result = await client.unsubscribe_resource(AnyUrl("file:///watched.txt"))

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

    server = Server("library")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name="touch", inputSchema={"type": "object"})]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        assert name == "touch"
        await server.request_context.session.send_resource_updated(AnyUrl("file:///watched.txt"))
        return [TextContent(type="text", text="touched")]

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        """Registered so the resources capability is advertised; the client never lists resources."""
        raise NotImplementedError

    @server.subscribe_resource()
    async def subscribe_resource(uri: AnyUrl) -> None:
        """Registered so the resources subscribe sub-capability is advertised; the client never subscribes."""
        raise NotImplementedError

    async with connect(server, message_handler=collect) as client:
        await client.call_tool("touch", {})
        with anyio.fail_after(5):
            await seen.wait()

    assert len(received) == 1
    assert isinstance(received[0], ServerNotification)
    assert isinstance(received[0].root, ResourceUpdatedNotification)
    assert received[0].root.params == snapshot(ResourceUpdatedNotificationParams(uri=AnyUrl("file:///watched.txt")))
