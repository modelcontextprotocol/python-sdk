import base64
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import pytest

import mcp.types as types
from mcp.client.client import Client
from mcp.server.lowlevel.server import Server
from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext


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
    async def list_resources(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=[types.Resource(uri=temp_file.as_uri(), name="Test")])

    async def read_resource(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.ReadResourceRequestParams,
    ) -> types.ReadResourceResult:
        return types.ReadResourceResult(
            contents=[types.TextResourceContents(uri=params.uri, text="Hello World", mime_type="text/plain")]
        )

    server = Server("test", on_list_resources=list_resources, on_read_resource=read_resource)

    async with Client(server) as client:
        result = await client.read_resource(temp_file.as_uri())
        assert len(result.contents) == 1

        content = result.contents[0]
        assert isinstance(content, types.TextResourceContents)
        assert content.text == "Hello World"
        assert content.mime_type == "text/plain"


@pytest.mark.anyio
async def test_read_resource_binary(temp_file: Path):
    async def list_resources(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=[types.Resource(uri=temp_file.as_uri(), name="Test")])

    async def read_resource(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.ReadResourceRequestParams,
    ) -> types.ReadResourceResult:
        return types.ReadResourceResult(
            contents=[
                types.BlobResourceContents(
                    uri=params.uri,
                    blob=base64.b64encode(b"Hello World").decode("utf-8"),
                    mime_type="application/octet-stream",
                )
            ]
        )

    server = Server("test", on_list_resources=list_resources, on_read_resource=read_resource)

    async with Client(server) as client:
        result = await client.read_resource(temp_file.as_uri())
        assert len(result.contents) == 1

        content = result.contents[0]
        assert isinstance(content, types.BlobResourceContents)
        assert content.mime_type == "application/octet-stream"


@pytest.mark.anyio
async def test_read_resource_default_mime(temp_file: Path):
    async def list_resources(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=[types.Resource(uri=temp_file.as_uri(), name="Test")])

    async def read_resource(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.ReadResourceRequestParams,
    ) -> types.ReadResourceResult:
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=params.uri,
                    text="Hello World",
                    # No mimeType specified
                )
            ]
        )

    server = Server("test", on_list_resources=list_resources, on_read_resource=read_resource)

    async with Client(server) as client:
        result = await client.read_resource(temp_file.as_uri())
        assert len(result.contents) == 1

        content = result.contents[0]
        assert isinstance(content, types.TextResourceContents)
        assert content.text == "Hello World"
