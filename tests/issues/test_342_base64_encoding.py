"""Test for base64 encoding issue in MCP server.

This test verifies that binary resource data is encoded with standard base64
(not urlsafe_b64encode), so BlobResourceContents validation succeeds.
"""

import base64

import pytest

from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import BlobResourceContents

pytestmark = pytest.mark.anyio


async def test_server_base64_encoding():
    """Tests that binary resource data round-trips correctly through base64 encoding.

    The test uses binary data that produces different results with urlsafe vs standard
    base64, ensuring the server uses standard encoding.
    """
    mcp = MCPServer("test")

    # Create binary data that will definitely result in + and / characters
    # when encoded with standard base64
    binary_data = bytes(list(range(255)) * 4)

    # Sanity check: our test data produces different encodings
    urlsafe_b64 = base64.urlsafe_b64encode(binary_data).decode()
    standard_b64 = base64.b64encode(binary_data).decode()
    assert urlsafe_b64 != standard_b64, "Test data doesn't demonstrate encoding difference"

    @mcp.resource("test://binary", mime_type="application/octet-stream")
    def get_binary() -> bytes:
        """Return binary test data."""
        return binary_data

    async with Client(mcp) as client:
        result = await client.read_resource("test://binary")
        assert len(result.contents) == 1

        blob_content = result.contents[0]
        assert isinstance(blob_content, BlobResourceContents)

        # Verify standard base64 was used (not urlsafe)
        assert blob_content.blob == standard_b64

        # Verify we can decode the data back correctly
        decoded = base64.b64decode(blob_content.blob)
        assert decoded == binary_data
