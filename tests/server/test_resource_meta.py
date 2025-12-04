"""Tests for _meta attribute support in resources."""

from collections.abc import Iterable
from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest
from pydantic import AnyUrl, FileUrl

import mcp.types as types
from mcp.server.lowlevel.server import ReadResourceContents, Server


@pytest.fixture
def temp_file():
    """Create a temporary file for testing."""
    with NamedTemporaryFile(mode="w", delete=False) as f:
        f.write("test content")
        path = Path(f.name).resolve()
    yield path
    try:
        path.unlink()
    except FileNotFoundError:  # pragma: no cover
        pass


@pytest.mark.anyio
async def test_read_resource_text_with_meta(temp_file: Path):
    """Test that _meta attributes are passed through for text resources."""
    server = Server("test")

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> Iterable[ReadResourceContents]:
        return [
            ReadResourceContents(
                content="Hello World",
                mime_type="text/plain",
                meta={"widgetDomain": "example.com", "custom": "value"},
            )
        ]

    # Get the handler directly from the server
    handler = server.request_handlers[types.ReadResourceRequest]

    # Create a request
    request = types.ReadResourceRequest(
        params=types.ReadResourceRequestParams(uri=FileUrl(temp_file.as_uri())),
    )

    # Call the handler
    result = await handler(request)
    assert isinstance(result.root, types.ReadResourceResult)
    assert len(result.root.contents) == 1

    content = result.root.contents[0]
    assert isinstance(content, types.TextResourceContents)
    assert content.text == "Hello World"
    assert content.mimeType == "text/plain"
    assert content.meta is not None
    assert content.meta["widgetDomain"] == "example.com"
    assert content.meta["custom"] == "value"


@pytest.mark.anyio
async def test_read_resource_binary_with_meta(temp_file: Path):
    """Test that _meta attributes are passed through for binary resources."""
    server = Server("test")

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> Iterable[ReadResourceContents]:
        return [
            ReadResourceContents(
                content=b"Hello World",
                mime_type="application/octet-stream",
                meta={"encoding": "base64", "size": 11},
            )
        ]

    # Get the handler directly from the server
    handler = server.request_handlers[types.ReadResourceRequest]

    # Create a request
    request = types.ReadResourceRequest(
        params=types.ReadResourceRequestParams(uri=FileUrl(temp_file.as_uri())),
    )

    # Call the handler
    result = await handler(request)
    assert isinstance(result.root, types.ReadResourceResult)
    assert len(result.root.contents) == 1

    content = result.root.contents[0]
    assert isinstance(content, types.BlobResourceContents)
    assert content.mimeType == "application/octet-stream"
    assert content.meta is not None
    assert content.meta["encoding"] == "base64"
    assert content.meta["size"] == 11


@pytest.mark.anyio
async def test_read_resource_without_meta(temp_file: Path):
    """Test that resources work correctly without _meta (backwards compatibility)."""
    server = Server("test")

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> Iterable[ReadResourceContents]:
        return [ReadResourceContents(content="Hello World", mime_type="text/plain")]

    # Get the handler directly from the server
    handler = server.request_handlers[types.ReadResourceRequest]

    # Create a request
    request = types.ReadResourceRequest(
        params=types.ReadResourceRequestParams(uri=FileUrl(temp_file.as_uri())),
    )

    # Call the handler
    result = await handler(request)
    assert isinstance(result.root, types.ReadResourceResult)
    assert len(result.root.contents) == 1

    content = result.root.contents[0]
    assert isinstance(content, types.TextResourceContents)
    assert content.text == "Hello World"
    assert content.mimeType == "text/plain"
    assert content.meta is None


@pytest.mark.anyio
async def test_read_resource_multiple_contents_with_meta(temp_file: Path):
    """Test multiple resource contents with different _meta values."""
    server = Server("test")

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> Iterable[ReadResourceContents]:
        return [
            ReadResourceContents(
                content="First content",
                mime_type="text/plain",
                meta={"index": 0, "type": "header"},
            ),
            ReadResourceContents(
                content="Second content",
                mime_type="text/plain",
                meta={"index": 1, "type": "body"},
            ),
        ]

    # Get the handler directly from the server
    handler = server.request_handlers[types.ReadResourceRequest]

    # Create a request
    request = types.ReadResourceRequest(
        params=types.ReadResourceRequestParams(uri=FileUrl(temp_file.as_uri())),
    )

    # Call the handler
    result = await handler(request)
    assert isinstance(result.root, types.ReadResourceResult)
    assert len(result.root.contents) == 2

    # Check first content
    content0 = result.root.contents[0]
    assert isinstance(content0, types.TextResourceContents)
    assert content0.text == "First content"
    assert content0.meta is not None
    assert content0.meta["index"] == 0
    assert content0.meta["type"] == "header"

    # Check second content
    content1 = result.root.contents[1]
    assert isinstance(content1, types.TextResourceContents)
    assert content1.text == "Second content"
    assert content1.meta is not None
    assert content1.meta["index"] == 1
    assert content1.meta["type"] == "body"


@pytest.mark.anyio
async def test_read_resource_meta_json_serialization(temp_file: Path):
    """Test that _meta is correctly serialized as '_meta' in JSON output."""
    server = Server("test")

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> Iterable[ReadResourceContents]:
        return [
            ReadResourceContents(
                content="Test content",
                mime_type="text/plain",
                meta={"widgetDomain": "example.com", "version": "1.0"},
            )
        ]

    # Get the handler
    handler = server.request_handlers[types.ReadResourceRequest]

    # Create a request
    request = types.ReadResourceRequest(
        params=types.ReadResourceRequestParams(uri=FileUrl(temp_file.as_uri())),
    )

    # Call the handler
    result = await handler(request)

    # Serialize to JSON with aliases
    result_json = result.model_dump(by_alias=True, mode="json")

    # Verify structure
    assert "root" in result_json
    assert "contents" in result_json["root"]
    assert len(result_json["root"]["contents"]) == 1

    # Verify _meta is in the JSON output (not "meta")
    content_json = result_json["root"]["contents"][0]
    assert "_meta" in content_json, "Expected '_meta' key in JSON output"
    assert "meta" not in content_json or content_json.get("meta") is None, "Should not have 'meta' key in JSON output"
    assert content_json["_meta"]["widgetDomain"] == "example.com"
    assert content_json["_meta"]["version"] == "1.0"

    # Also verify in the JSON string
    result_json_str = result.model_dump_json(by_alias=True)
    assert '"_meta"' in result_json_str, "Expected '_meta' string in JSON output"
    assert content_json["_meta"]["widgetDomain"] == "example.com"
