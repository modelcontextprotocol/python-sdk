import base64
from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel.server import Server


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
    async def handle_read_resource(
        ctx: ServerRequestContext, params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=str(params.uri),
                    text="Hello World",
                    mime_type="text/plain",
                )
            ]
        )

    server = Server("test", on_read_resource=handle_read_resource)

    # Get the handler directly from the server
    handler = server._request_handlers["resources/read"]

    # Create a mock context
    from unittest.mock import MagicMock

    mock_ctx = MagicMock(spec=ServerRequestContext)

    # Create params
    params = types.ReadResourceRequestParams(uri=temp_file.as_uri())

    # Call the handler
    result = await handler(mock_ctx, params)
    assert isinstance(result, types.ReadResourceResult)
    assert len(result.contents) == 1

    content = result.contents[0]
    assert isinstance(content, types.TextResourceContents)
    assert content.text == "Hello World"
    assert content.mime_type == "text/plain"


@pytest.mark.anyio
async def test_read_resource_binary(temp_file: Path):
    async def handle_read_resource(
        ctx: ServerRequestContext, params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        return types.ReadResourceResult(
            contents=[
                types.BlobResourceContents(
                    uri=str(params.uri),
                    blob=base64.standard_b64encode(b"Hello World").decode(),
                    mime_type="application/octet-stream",
                )
            ]
        )

    server = Server("test", on_read_resource=handle_read_resource)

    # Get the handler directly from the server
    handler = server._request_handlers["resources/read"]

    # Create a mock context
    from unittest.mock import MagicMock

    mock_ctx = MagicMock(spec=ServerRequestContext)

    # Create params
    params = types.ReadResourceRequestParams(uri=temp_file.as_uri())

    # Call the handler
    result = await handler(mock_ctx, params)
    assert isinstance(result, types.ReadResourceResult)
    assert len(result.contents) == 1

    content = result.contents[0]
    assert isinstance(content, types.BlobResourceContents)
    assert content.mime_type == "application/octet-stream"


@pytest.mark.anyio
async def test_read_resource_default_mime(temp_file: Path):
    async def handle_read_resource(
        ctx: ServerRequestContext, params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=str(params.uri),
                    text="Hello World",
                    mime_type="text/plain",
                )
            ]
        )

    server = Server("test", on_read_resource=handle_read_resource)

    # Get the handler directly from the server
    handler = server._request_handlers["resources/read"]

    # Create a mock context
    from unittest.mock import MagicMock

    mock_ctx = MagicMock(spec=ServerRequestContext)

    # Create params
    params = types.ReadResourceRequestParams(uri=temp_file.as_uri())

    # Call the handler
    result = await handler(mock_ctx, params)
    assert isinstance(result, types.ReadResourceResult)
    assert len(result.contents) == 1

    content = result.contents[0]
    assert isinstance(content, types.TextResourceContents)
    assert content.text == "Hello World"
    assert content.mime_type == "text/plain"
