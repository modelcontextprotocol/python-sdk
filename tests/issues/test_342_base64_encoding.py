"""Test for base64 encoding issue in MCP server.

This test demonstrates the issue in server.py where the server uses
urlsafe_b64encode but the BlobResourceContents validator expects standard
base64 encoding.

The test should FAIL before fixing server.py to use b64encode instead of
urlsafe_b64encode.
After the fix, the test should PASS.
"""

import base64
from typing import cast

import pytest
from pydantic import AnyUrl

from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.lowlevel.server import Server
from mcp.types import (
    BlobResourceContents,
    ReadResourceRequest,
    ReadResourceRequestParams,
    ReadResourceResult,
    ServerResult,
)


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
    server = Server("test")

    # Create binary data that will definitely result in + and / characters
    # when encoded with standard base64
    binary_data = bytes([x for x in range(255)] * 4)

    # Register a resource handler that returns our test data
    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        return [
            ReadResourceContents(
                content=binary_data, mime_type="application/octet-stream"
            )
        ]

    # Get the handler directly from the server
    handler = server.request_handlers[ReadResourceRequest]

    # Create a request
    request = ReadResourceRequest(
        method="resources/read",
        params=ReadResourceRequestParams(uri=AnyUrl("test://resource")),
    )

    # Call the handler to get the response
    result: ServerResult = await handler(request)

    # After (fixed code):
    read_result: ReadResourceResult = cast(ReadResourceResult, result.root)
    blob_content = read_result.contents[0]

    # First verify our test data actually produces different encodings
    urlsafe_b64 = base64.urlsafe_b64encode(binary_data).decode()
    standard_b64 = base64.b64encode(binary_data).decode()
    assert urlsafe_b64 != standard_b64, "Test data doesn't demonstrate"
    " encoding difference"

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
