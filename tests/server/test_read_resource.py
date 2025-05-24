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
async def test_read_resource_text(temp_file: Path):
    server = Server("test")

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> Iterable[ReadResourceContents]:
        return [ReadResourceContents(content="Hello World", mime_type="text/plain")]

    # Get the handler directly from the server
    handler = server.request_handlers[types.ReadResourceRequest]

    # Create a request
    request = types.ReadResourceRequest(
        method="resources/read",
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


@pytest.mark.anyio
async def test_read_resource_binary(temp_file: Path):
    server = Server("test")

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> Iterable[ReadResourceContents]:
        return [
            ReadResourceContents(
                content=b"Hello World", mime_type="application/octet-stream"
            )
        ]

    # Get the handler directly from the server
    handler = server.request_handlers[types.ReadResourceRequest]

    # Create a request
    request = types.ReadResourceRequest(
        method="resources/read",
        params=types.ReadResourceRequestParams(uri=FileUrl(temp_file.as_uri())),
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
    async def read_resource(uri: AnyUrl) -> Iterable[ReadResourceContents]:
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
        method="resources/read",
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
