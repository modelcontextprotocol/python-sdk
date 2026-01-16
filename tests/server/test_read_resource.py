from collections.abc import Iterable
from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

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
async def test_read_resource_text(temp_file: Path):
    server = Server("test")

    @server.read_resource()
    async def read_resource(uri: str) -> Iterable[ReadResourceContents]:
        return [ReadResourceContents(content="Hello World", mime_type="text/plain")]

    # Get the handler directly from the server
    handler = server.request_handlers[types.ReadResourceRequest]

    # Create a request
    request = types.ReadResourceRequest(
        params=types.ReadResourceRequestParams(uri=temp_file.as_uri()),
    )

    # Call the handler
    result = await handler(request)
    assert isinstance(result.root, types.ReadResourceResult)
    assert len(result.root.contents) == 1

    content = result.root.contents[0]
    assert isinstance(content, types.TextResourceContents)
    assert content.text == "Hello World"
    assert content.mimeType == "text/plain"


@pytest.mark.anyio
async def test_read_resource_binary(temp_file: Path):
    server = Server("test")

    @server.read_resource()
    async def read_resource(uri: str) -> Iterable[ReadResourceContents]:
        return [ReadResourceContents(content=b"Hello World", mime_type="application/octet-stream")]

    # Get the handler directly from the server
    handler = server.request_handlers[types.ReadResourceRequest]

    # Create a request
    request = types.ReadResourceRequest(
        params=types.ReadResourceRequestParams(uri=temp_file.as_uri()),
    )

    # Call the handler
    result = await handler(request)
    assert isinstance(result.root, types.ReadResourceResult)
    assert len(result.root.contents) == 1

    content = result.root.contents[0]
    assert isinstance(content, types.BlobResourceContents)
    assert content.mimeType == "application/octet-stream"


@pytest.mark.anyio
async def test_read_resource_default_mime(temp_file: Path):
    server = Server("test")

    @server.read_resource()
    async def read_resource(uri: str) -> Iterable[ReadResourceContents]:
        return [
            ReadResourceContents(
                content="Hello World",
                # No mime_type specified, should default to text/plain
            )
        ]

    # Get the handler directly from the server
    handler = server.request_handlers[types.ReadResourceRequest]

    # Create a request
    request = types.ReadResourceRequest(
        params=types.ReadResourceRequestParams(uri=temp_file.as_uri()),
    )

    # Call the handler
    result = await handler(request)
    assert isinstance(result.root, types.ReadResourceResult)
    assert len(result.root.contents) == 1

    content = result.root.contents[0]
    assert isinstance(content, types.TextResourceContents)
    assert content.text == "Hello World"
    assert content.mimeType == "text/plain"


@pytest.mark.anyio
async def test_read_resource_with_meta(temp_file: Path):
    """Test that meta from ReadResourceContents is forwarded to ReadResourceResult._meta."""
    server = Server("test")

    test_meta = {"ui": {"csp": {"connectDomains": ["https://cdn.example.com"]}}}

    @server.read_resource()
    async def read_resource(uri: str) -> Iterable[ReadResourceContents]:
        return [ReadResourceContents(content="<html></html>", mime_type="text/html", meta=test_meta)]

    handler = server.request_handlers[types.ReadResourceRequest]

    request = types.ReadResourceRequest(
        params=types.ReadResourceRequestParams(uri=temp_file.as_uri()),
    )

    result = await handler(request)
    assert isinstance(result.root, types.ReadResourceResult)

    # Verify _meta is forwarded to ReadResourceResult level
    assert result.root.meta == test_meta

    # Also verify it's on the content
    content = result.root.contents[0]
    assert isinstance(content, types.TextResourceContents)
    assert content.meta == test_meta


@pytest.mark.anyio
async def test_read_resource_meta_from_first_content(temp_file: Path):
    """Test that first non-None meta is used for ReadResourceResult._meta."""
    server = Server("test")

    meta1 = {"source": "first"}
    meta2 = {"source": "second"}

    @server.read_resource()
    async def read_resource(uri: str) -> Iterable[ReadResourceContents]:
        return [
            ReadResourceContents(content="content1", mime_type="text/plain", meta=meta1),
            ReadResourceContents(content="content2", mime_type="text/plain", meta=meta2),
        ]

    handler = server.request_handlers[types.ReadResourceRequest]

    request = types.ReadResourceRequest(
        params=types.ReadResourceRequestParams(uri=temp_file.as_uri()),
    )

    result = await handler(request)
    assert isinstance(result.root, types.ReadResourceResult)

    # First content's meta should be used for result-level _meta
    assert result.root.meta == meta1

    # Each content should have its own meta
    assert result.root.contents[0].meta == meta1
    assert result.root.contents[1].meta == meta2
