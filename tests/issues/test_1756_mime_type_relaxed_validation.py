"""Test for Github issue #1756: Consider removing or relaxing MIME type validation in FastMCP resources.

The validation regex for FastMCP Resource's mime_type field is too strict and does not allow valid MIME types.
Ex: parameter values with quotes strings and valid token characters (e.g. !, #, *, +, etc.) were rejected.
"""

import pytest
from pydantic import AnyUrl, ValidationError

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import (
    create_connected_server_and_client_session as client_session,
)

pytestmark = pytest.mark.anyio


# Exhaustive list of valid mime types formats.
# https://www.iana.org/assignments/media-types/media-types.xhtml
def _test_data_mime_type_with_valid_rfc2045_formats():
    """Test data for valid mime types with rfc2045 formats."""
    return [
        # Standard types
        ("application/json", "Simple application type"),
        ("text/html", "Simple text type"),
        ("image/png", "Simple image type"),
        ("audio/mpeg", "Simple audio type"),
        ("video/mp4", "Simple video type"),
        ("font/woff2", "Simple font type"),
        ("model/gltf+json", "Model type"),
        # Vendor specific (vnd)
        ("application/vnd.api+json", "Vendor specific JSON api"),
        ("application/vnd.ms-excel", "Vendor specific Excel"),
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "Complex vendor type"),
        # Parameters
        ('text/plain; charset="utf-8"', "MIME type with quotes in parameter value"),
        ('text/plain; charset="utf!8"', "MIME type with exclamation mark in parameter value"),
        ('text/plain; charset="utf*8"', "MIME type with asterisk in parameter value"),
        ('text/plain; charset="utf#8"', "MIME type with hash in parameter value"),
        ('text/plain; charset="utf+8"', "MIME type with plus in parameter value"),
        ("text/plain; charset=utf-8; format=flowed", "Multiple parameters"),
        ("multipart/form-data; boundary=---1234", "Multipart with boundary"),
        # Special characters in subtype
        ("image/svg+xml", "Subtype with plus"),
        # Parmeter issues.
        ("text/plain; charset=utf 8", "Unquoted space in parameter"),
        ('text/plain; charset="utf-8', "Unbalanced quotes"),
        ("text/plain; charset", "Parameter missing value"),
    ]


@pytest.mark.parametrize("mime_type, description", _test_data_mime_type_with_valid_rfc2045_formats())
async def test_mime_type_with_valid_rfc2045_formats(mime_type: str, description: str):
    """Test that MIME type with valid RFC 2045 token characters are accepted."""
    mcp = FastMCP("test")

    @mcp.resource("ui://widget", mime_type=mime_type)
    def widget() -> str:
        raise NotImplementedError()

    resources = await mcp.list_resources()
    assert len(resources) == 1
    assert resources[0].mimeType == mime_type


@pytest.mark.parametrize("mime_type, description", _test_data_mime_type_with_valid_rfc2045_formats())
async def test_mime_type_preserved_in_read_resource(mime_type: str, description: str):
    """Test that MIME type with parameters is preserved when reading resource."""
    mcp = FastMCP("test")

    @mcp.resource("ui://my-widget", mime_type=mime_type)
    def my_widget() -> str:
        return "<html><body>Hello MCP-UI</body></html>"

    async with client_session(mcp._mcp_server) as client:
        # Read the resource
        result = await client.read_resource(AnyUrl("ui://my-widget"))
        assert len(result.contents) == 1
        assert result.contents[0].mimeType == mime_type


def _test_data_mime_type_with_invalid_rfc2045_formats():
    """Test data for invalid mime types with rfc2045 formats."""
    return [
        ("charset=utf-8", "MIME type with no main and subtype but only parameters."),
        ("text", "Missing subtype"),
        ("text/", "Empty subtype"),
        ("/html", "Missing type"),
        (" ", "Whitespace"),
        # --- Structural ---
        ("text//plain", "Double slash"),
        ("application/json/", "Trailing slash"),
        ("text / plain", "Spaces around primary slash"),
        # --- Illegal Characters ---
        ("image/jp@g", "Illegal character in subtype"),
        ("text(comment)/plain", "Comments inside type name"),
        # --- Parameter Issues ---
        ("text/plain; =utf-8", "Parameter missing key"),
        ("text/plain charset=utf-8", "Missing semicolon separator"),
        # --- Encoding/Non-ASCII ---
        ("text/plâin", "Non-ASCII character in subtype"),
    ]


@pytest.mark.parametrize("mime_type, description", _test_data_mime_type_with_invalid_rfc2045_formats())
async def test_mime_type_with_invalid_rfc2045_formats(mime_type: str, description: str):
    """Test that MIME type with invalid RFC 2045 token characters are rejected."""
    mcp = FastMCP("test")

    with pytest.raises(ValidationError):

        @mcp.resource("ui://widget", mime_type=mime_type)
        def widget() -> str:
            raise NotImplementedError()
