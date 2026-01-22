import base64

import pytest

from mcp import Client, types
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents

pytestmark = pytest.mark.anyio


async def test_fastmcp_resource_mime_type():
    """Test that mime_type parameter is respected for resources."""
    mcp = FastMCP("test")

    # Create a small test image as bytes
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

    # Test that resources are listed with correct mime type
    async with Client(mcp) as client:
        # List resources and verify mime types
        resources = await client.list_resources()
        assert resources.resources is not None

        mapping = {str(r.uri): r for r in resources.resources}

        # Find our resources
        string_resource = mapping["test://image"]
        bytes_resource = mapping["test://image_bytes"]

        # Verify mime types
        assert string_resource.mime_type == "image/png", "String resource mime type not respected"
        assert bytes_resource.mime_type == "image/png", "Bytes resource mime type not respected"

        # Also verify the content can be read correctly
        string_result = await client.read_resource("test://image")
        assert len(string_result.contents) == 1
        assert getattr(string_result.contents[0], "text") == base64_string, "Base64 string mismatch"
        assert string_result.contents[0].mime_type == "image/png", "String content mime type not preserved"

        bytes_result = await client.read_resource("test://image_bytes")
        assert len(bytes_result.contents) == 1
        assert base64.b64decode(getattr(bytes_result.contents[0], "blob")) == image_bytes, "Bytes mismatch"
        assert bytes_result.contents[0].mime_type == "image/png", "Bytes content mime type not preserved"


async def test_lowlevel_resource_mime_type():
    """Test that mime_type parameter is respected for resources."""
    server = Server("test")

    # Create a small test image as bytes
    image_bytes = b"fake_image_data"
    base64_string = base64.b64encode(image_bytes).decode("utf-8")

    # Create test resources with specific mime types
    test_resources = [
        types.Resource(uri="test://image", name="test image", mime_type="image/png"),
        types.Resource(
            uri="test://image_bytes",
            name="test image bytes",
            mime_type="image/png",
        ),
    ]

    @server.list_resources()
    async def handle_list_resources():
        return test_resources

    @server.read_resource()
    async def handle_read_resource(uri: str):
        if str(uri) == "test://image":
            return [ReadResourceContents(content=base64_string, mime_type="image/png")]
        elif str(uri) == "test://image_bytes":
            return [ReadResourceContents(content=bytes(image_bytes), mime_type="image/png")]
        raise Exception(f"Resource not found: {uri}")  # pragma: no cover

    # Test that resources are listed with correct mime type
    async with Client(server) as client:
        # List resources and verify mime types
        resources = await client.list_resources()
        assert resources.resources is not None

        mapping = {str(r.uri): r for r in resources.resources}

        # Find our resources
        string_resource = mapping["test://image"]
        bytes_resource = mapping["test://image_bytes"]

        # Verify mime types
        assert string_resource.mime_type == "image/png", "String resource mime type not respected"
        assert bytes_resource.mime_type == "image/png", "Bytes resource mime type not respected"

        # Also verify the content can be read correctly
        string_result = await client.read_resource("test://image")
        assert len(string_result.contents) == 1
        assert getattr(string_result.contents[0], "text") == base64_string, "Base64 string mismatch"
        assert string_result.contents[0].mime_type == "image/png", "String content mime type not preserved"

        bytes_result = await client.read_resource("test://image_bytes")
        assert len(bytes_result.contents) == 1
        assert base64.b64decode(getattr(bytes_result.contents[0], "blob")) == image_bytes, "Bytes mismatch"
        assert bytes_result.contents[0].mime_type == "image/png", "Bytes content mime type not preserved"
