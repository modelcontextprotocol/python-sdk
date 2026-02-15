import base64

import pytest

from mcp import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    BlobResourceContents,
    ReadResourceRequestParams,
    ReadResourceResult,
    TextResourceContents,
)

pytestmark = pytest.mark.anyio


async def test_read_resource_text():
    async def handle_read_resource(ctx: ServerRequestContext, params: ReadResourceRequestParams) -> ReadResourceResult:
        return ReadResourceResult(
            contents=[TextResourceContents(uri=str(params.uri), text="Hello World", mime_type="text/plain")]
        )

    server = Server("test", on_read_resource=handle_read_resource)

    async with Client(server) as client:
        result = await client.read_resource("test://resource")
        assert len(result.contents) == 1

        content = result.contents[0]
        assert isinstance(content, TextResourceContents)
        assert content.text == "Hello World"
        assert content.mime_type == "text/plain"


async def test_read_resource_binary():
    binary_data = b"Hello World"

    async def handle_read_resource(ctx: ServerRequestContext, params: ReadResourceRequestParams) -> ReadResourceResult:
        return ReadResourceResult(
            contents=[
                BlobResourceContents(
                    uri=str(params.uri),
                    blob=base64.b64encode(binary_data).decode("utf-8"),
                    mime_type="application/octet-stream",
                )
            ]
        )

    server = Server("test", on_read_resource=handle_read_resource)

    async with Client(server) as client:
        result = await client.read_resource("test://resource")
        assert len(result.contents) == 1

        content = result.contents[0]
        assert isinstance(content, BlobResourceContents)
        assert content.mime_type == "application/octet-stream"
        assert base64.b64decode(content.blob) == binary_data
