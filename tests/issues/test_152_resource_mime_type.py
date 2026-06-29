import base64

import mcp_types as types
import pytest
from mcp_types import (
    BlobResourceContents,
    ListResourcesResult,
    PaginatedRequestParams,
    ReadResourceRequestParams,
    ReadResourceResult,
    TextResourceContents,
)

from mcp import Client
from mcp.server import Server, ServerRequestContext
from mcp.server.mcpserver import MCPServer

pytestmark = pytest.mark.anyio


async def test_mcpserver_resource_mime_type():
    mcp = MCPServer("test")

    image_bytes = b"fake_image_data"
    base64_string = base64.b64encode(image_bytes).decode("utf-8")

    @mcp.resource("test://image", mime_type="image/png")
    def get_image_as_string() -> str:
        """Return a test image as base64 string."""
        return base64_string

    @mcp.resource("test://image_bytes", mime_type="image/png")
    def get_image_as_bytes() -> bytes:
        """Return a test image as bytes."""
        return image_bytes

    async with Client(mcp) as client:
        resources = await client.list_resources()
        assert resources.resources is not None

        mapping = {str(r.uri): r for r in resources.resources}

        string_resource = mapping["test://image"]
        bytes_resource = mapping["test://image_bytes"]

        assert string_resource.mime_type == "image/png", "String resource mime type not respected"
        assert bytes_resource.mime_type == "image/png", "Bytes resource mime type not respected"

        string_result = await client.read_resource("test://image")
        assert len(string_result.contents) == 1
        assert getattr(string_result.contents[0], "text") == base64_string, "Base64 string mismatch"
        assert string_result.contents[0].mime_type == "image/png", "String content mime type not preserved"

        bytes_result = await client.read_resource("test://image_bytes")
        assert len(bytes_result.contents) == 1
        assert base64.b64decode(getattr(bytes_result.contents[0], "blob")) == image_bytes, "Bytes mismatch"
        assert bytes_result.contents[0].mime_type == "image/png", "Bytes content mime type not preserved"


async def test_lowlevel_resource_mime_type():
    image_bytes = b"fake_image_data"
    base64_string = base64.b64encode(image_bytes).decode("utf-8")

    test_resources = [
        types.Resource(uri="test://image", name="test image", mime_type="image/png"),
        types.Resource(
            uri="test://image_bytes",
            name="test image bytes",
            mime_type="image/png",
        ),
    ]

    async def handle_list_resources(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListResourcesResult:
        return ListResourcesResult(resources=test_resources)

    resource_contents: dict[str, list[TextResourceContents | BlobResourceContents]] = {
        "test://image": [TextResourceContents(uri="test://image", text=base64_string, mime_type="image/png")],
        "test://image_bytes": [
            BlobResourceContents(
                uri="test://image_bytes", blob=base64.b64encode(image_bytes).decode("utf-8"), mime_type="image/png"
            )
        ],
    }

    async def handle_read_resource(ctx: ServerRequestContext, params: ReadResourceRequestParams) -> ReadResourceResult:
        return ReadResourceResult(contents=resource_contents[str(params.uri)])

    server = Server("test", on_list_resources=handle_list_resources, on_read_resource=handle_read_resource)

    async with Client(server) as client:
        resources = await client.list_resources()
        assert resources.resources is not None

        mapping = {str(r.uri): r for r in resources.resources}

        string_resource = mapping["test://image"]
        bytes_resource = mapping["test://image_bytes"]

        assert string_resource.mime_type == "image/png", "String resource mime type not respected"
        assert bytes_resource.mime_type == "image/png", "Bytes resource mime type not respected"

        string_result = await client.read_resource("test://image")
        assert len(string_result.contents) == 1
        assert getattr(string_result.contents[0], "text") == base64_string, "Base64 string mismatch"
        assert string_result.contents[0].mime_type == "image/png", "String content mime type not preserved"

        bytes_result = await client.read_resource("test://image_bytes")
        assert len(bytes_result.contents) == 1
        assert base64.b64decode(getattr(bytes_result.contents[0], "blob")) == image_bytes, "Bytes mismatch"
        assert bytes_result.contents[0].mime_type == "image/png", "Bytes content mime type not preserved"
