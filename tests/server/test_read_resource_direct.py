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
    except FileNotFoundError:
        pass


@pytest.mark.anyio
async def test_read_resource_direct_text_resource_contents(temp_file: Path):
    """Test returning TextResourceContents directly from read_resource handler."""
    server = Server("test")

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> Iterable[types.TextResourceContents]:
        return [
            types.TextResourceContents(
                uri=uri,
                text="Direct text content",
                mimeType="text/markdown",
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
    assert content.text == "Direct text content"
    assert content.mimeType == "text/markdown"
    assert str(content.uri) == temp_file.as_uri()


@pytest.mark.anyio
async def test_read_resource_direct_blob_resource_contents(temp_file: Path):
    """Test returning BlobResourceContents directly from read_resource handler."""
    server = Server("test")

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> Iterable[types.BlobResourceContents]:
        return [
            types.BlobResourceContents(
                uri=uri,
                blob="SGVsbG8gV29ybGQ=",  # "Hello World" in base64
                mimeType="application/pdf",
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
    assert content.blob == "SGVsbG8gV29ybGQ="
    assert content.mimeType == "application/pdf"
    assert str(content.uri) == temp_file.as_uri()


@pytest.mark.anyio
async def test_read_resource_mixed_contents(temp_file: Path):
    """Test mixing direct ResourceContents with ReadResourceContents."""
    server = Server("test")

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> Iterable[ReadResourceContents | types.TextResourceContents]:
        return [
            types.TextResourceContents(
                uri=uri,
                text="Direct ResourceContents",
                mimeType="text/plain",
            ),
            ReadResourceContents(content="Wrapped content", mime_type="text/html"),
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

    # First content is direct ResourceContents
    content1 = result.root.contents[0]
    assert isinstance(content1, types.TextResourceContents)
    assert content1.text == "Direct ResourceContents"
    assert content1.mimeType == "text/plain"

    # Second content is wrapped ReadResourceContents
    content2 = result.root.contents[1]
    assert isinstance(content2, types.TextResourceContents)
    assert content2.text == "Wrapped content"
    assert content2.mimeType == "text/html"


@pytest.mark.anyio
async def test_read_resource_multiple_resource_contents(temp_file: Path):
    """Test returning multiple ResourceContents objects."""
    server = Server("test")

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> Iterable[types.TextResourceContents | types.BlobResourceContents]:
        return [
            types.TextResourceContents(
                uri=uri,
                text="First text content",
                mimeType="text/plain",
            ),
            types.BlobResourceContents(
                uri=uri,
                blob="U2Vjb25kIGNvbnRlbnQ=",  # "Second content" in base64
                mimeType="application/octet-stream",
            ),
            types.TextResourceContents(
                uri=uri,
                text="Third text content",
                mimeType="text/markdown",
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
    assert len(result.root.contents) == 3

    # Check first content
    content1 = result.root.contents[0]
    assert isinstance(content1, types.TextResourceContents)
    assert content1.text == "First text content"
    assert content1.mimeType == "text/plain"

    # Check second content
    content2 = result.root.contents[1]
    assert isinstance(content2, types.BlobResourceContents)
    assert content2.blob == "U2Vjb25kIGNvbnRlbnQ="
    assert content2.mimeType == "application/octet-stream"

    # Check third content
    content3 = result.root.contents[2]
    assert isinstance(content3, types.TextResourceContents)
    assert content3.text == "Third text content"
    assert content3.mimeType == "text/markdown"