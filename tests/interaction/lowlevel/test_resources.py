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
    ErrorData,
    ListResourcesResult,
    ReadResourceResult,
    Resource,
    TextResourceContents,
)
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
