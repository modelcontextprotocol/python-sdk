"""Test FastMCP resources returning ResourceContents directly."""

import pytest
from pydantic import AnyUrl

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources import TextResource
from mcp.types import BlobResourceContents, TextResourceContents


@pytest.mark.anyio
async def test_resource_returns_text_resource_contents_directly():
    """Test a custom resource that returns TextResourceContents directly."""
    app = FastMCP("test")

    class DirectTextResource(TextResource):
        """A resource that returns TextResourceContents directly."""

        async def read(self):
            # Return TextResourceContents directly instead of str
            return TextResourceContents(
                uri=self.uri,
                text="Direct TextResourceContents content",
                mimeType="text/markdown",
            )

    # Add the resource
    app.add_resource(
        DirectTextResource(
            uri="resource://direct-text",
            name="direct-text",
            title="Direct Text Resource",
            description="Returns TextResourceContents directly",
            text="This is ignored since we override read()",
        )
    )

    # Read the resource
    contents = await app.read_resource("resource://direct-text")
    contents_list = list(contents)

    # Verify the result
    assert len(contents_list) == 1
    content = contents_list[0]
    assert isinstance(content, TextResourceContents)
    assert content.text == "Direct TextResourceContents content"
    assert content.mimeType == "text/markdown"
    assert str(content.uri) == "resource://direct-text"


@pytest.mark.anyio
async def test_resource_returns_blob_resource_contents_directly():
    """Test a custom resource that returns BlobResourceContents directly."""
    app = FastMCP("test")

    class DirectBlobResource(TextResource):
        """A resource that returns BlobResourceContents directly."""

        async def read(self):
            # Return BlobResourceContents directly
            return BlobResourceContents(
                uri=self.uri,
                blob="SGVsbG8gRmFzdE1DUA==",  # "Hello FastMCP" in base64
                mimeType="application/pdf",
            )

    # Add the resource
    app.add_resource(
        DirectBlobResource(
            uri="resource://direct-blob",
            name="direct-blob",
            title="Direct Blob Resource",
            description="Returns BlobResourceContents directly",
            text="This is ignored since we override read()",
        )
    )

    # Read the resource
    contents = await app.read_resource("resource://direct-blob")
    contents_list = list(contents)

    # Verify the result
    assert len(contents_list) == 1
    content = contents_list[0]
    assert isinstance(content, BlobResourceContents)
    assert content.blob == "SGVsbG8gRmFzdE1DUA=="
    assert content.mimeType == "application/pdf"
    assert str(content.uri) == "resource://direct-blob"


@pytest.mark.anyio
async def test_function_resource_returns_resource_contents():
    """Test function resource returning ResourceContents directly."""
    app = FastMCP("test")

    @app.resource("resource://function-text-contents")
    async def get_text_contents() -> TextResourceContents:
        """Return TextResourceContents directly from function resource."""
        return TextResourceContents(
            uri=AnyUrl("resource://function-text-contents"),
            text="Function returned TextResourceContents",
            mimeType="text/x-python",
        )

    @app.resource("resource://function-blob-contents")
    def get_blob_contents() -> BlobResourceContents:
        """Return BlobResourceContents directly from function resource."""
        return BlobResourceContents(
            uri=AnyUrl("resource://function-blob-contents"),
            blob="RnVuY3Rpb24gYmxvYg==",  # "Function blob" in base64
            mimeType="image/png",
        )

    # Read text resource
    text_contents = await app.read_resource("resource://function-text-contents")
    text_list = list(text_contents)
    assert len(text_list) == 1
    text_content = text_list[0]
    assert isinstance(text_content, TextResourceContents)
    assert text_content.text == "Function returned TextResourceContents"
    assert text_content.mimeType == "text/x-python"

    # Read blob resource
    blob_contents = await app.read_resource("resource://function-blob-contents")
    blob_list = list(blob_contents)
    assert len(blob_list) == 1
    blob_content = blob_list[0]
    assert isinstance(blob_content, BlobResourceContents)
    assert blob_content.blob == "RnVuY3Rpb24gYmxvYg=="
    assert blob_content.mimeType == "image/png"


@pytest.mark.anyio
async def test_mixed_traditional_and_direct_resources():
    """Test server with both traditional and direct ResourceContents resources."""
    app = FastMCP("test")

    # Traditional string resource
    @app.resource("resource://traditional")
    def traditional_resource() -> str:
        return "Traditional string content"

    # Direct ResourceContents resource
    @app.resource("resource://direct")
    def direct_resource() -> TextResourceContents:
        return TextResourceContents(
            uri=AnyUrl("resource://direct"),
            text="Direct ResourceContents content",
            mimeType="text/html",
        )

    # Read traditional resource (will be wrapped)
    trad_contents = await app.read_resource("resource://traditional")
    trad_list = list(trad_contents)
    assert len(trad_list) == 1
    # The content type might be ReadResourceContents, but we're checking the behavior

    # Read direct ResourceContents
    direct_contents = await app.read_resource("resource://direct")
    direct_list = list(direct_contents)
    assert len(direct_list) == 1
    direct_content = direct_list[0]
    assert isinstance(direct_content, TextResourceContents)
    assert direct_content.text == "Direct ResourceContents content"
    assert direct_content.mimeType == "text/html"


@pytest.mark.anyio
async def test_resource_template_returns_resource_contents():
    """Test resource template returning ResourceContents directly."""
    app = FastMCP("test")

    @app.resource("resource://{category}/{item}")
    async def get_item_contents(category: str, item: str) -> TextResourceContents:
        """Return TextResourceContents for template resource."""
        return TextResourceContents(
            uri=AnyUrl(f"resource://{category}/{item}"),
            text=f"Content for {item} in {category}",
            mimeType="text/plain",
        )

    # Read templated resource
    contents = await app.read_resource("resource://books/python")
    contents_list = list(contents)
    assert len(contents_list) == 1
    content = contents_list[0]
    assert isinstance(content, TextResourceContents)
    assert content.text == "Content for python in books"
    assert content.mimeType == "text/plain"
    assert str(content.uri) == "resource://books/python"