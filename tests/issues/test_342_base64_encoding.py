"""Test for base64 encoding issue in MCP server.

This test demonstrates the issue in server.py where the server uses
urlsafe_b64encode but the BlobResourceContents validator expects standard
base64 encoding.

The test should FAIL before fixing server.py to use b64encode instead of
urlsafe_b64encode.
After the fix, the test should PASS.
"""

import base64
from typing import Any

import pytest

from mcp import Client, types
from mcp.server.lowlevel.server import Server
from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext
from mcp.types import BlobResourceContents


@pytest.mark.anyio
async def test_server_base64_encoding_issue():
    """Tests that server response can be validated by BlobResourceContents.

    This test will:
    1. Set up a server that returns binary data
    2. Extract the base64-encoded blob from the server's response
    3. Verify the encoded data can be properly validated by BlobResourceContents

    BEFORE FIX: The test will fail because server uses urlsafe_b64encode
    AFTER FIX: The test will pass because server uses standard b64encode
    """
    # Create binary data that will definitely result in + and / characters
    # when encoded with standard base64
    binary_data = bytes(list(range(255)) * 4)

    # Register a resource handler that returns our test data
    async def on_read_resource(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.ReadResourceRequestParams,
    ) -> types.ReadResourceResult:
        return types.ReadResourceResult(
            contents=[
                types.BlobResourceContents(
                    uri=str(params.uri),
                    blob=base64.b64encode(binary_data).decode("utf-8"),
                    mime_type="application/octet-stream",
                )
            ]
        )

    server = Server("test", on_read_resource=on_read_resource)

    async with Client(server) as client:
        # Read the resource through the proper client interface
        result = await client.read_resource("test://resource")

        # Get the blob content
        blob_content = result.contents[0]

        # First verify our test data actually produces different encodings
        urlsafe_b64 = base64.urlsafe_b64encode(binary_data).decode()
        standard_b64 = base64.b64encode(binary_data).decode()
        assert urlsafe_b64 != standard_b64, "Test data doesn't demonstrate encoding difference"

        # Now validate the server's output with BlobResourceContents.model_validate
        # Before the fix: This should fail with "Invalid base64" because server
        # uses urlsafe_b64encode
        # After the fix: This should pass because server will use standard b64encode
        model_dict = blob_content.model_dump()

        # Direct validation - this will fail before fix, pass after fix
        blob_model = BlobResourceContents.model_validate(model_dict)

        # Verify we can decode the data back correctly
        decoded = base64.b64decode(blob_model.blob)
        assert decoded == binary_data
