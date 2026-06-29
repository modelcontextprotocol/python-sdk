"""Issue #342 regression: binary resource data must use standard base64, not urlsafe_b64encode."""

import base64

import pytest
from mcp_types import BlobResourceContents

from mcp import Client
from mcp.server.mcpserver import MCPServer

pytestmark = pytest.mark.anyio


async def test_server_base64_encoding():
    mcp = MCPServer("test")

    # Data containing + and / when standard-encoded, so urlsafe and standard outputs differ
    binary_data = bytes(list(range(255)) * 4)

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

        assert blob_content.blob == standard_b64

        decoded = base64.b64decode(blob_content.blob)
        assert decoded == binary_data
