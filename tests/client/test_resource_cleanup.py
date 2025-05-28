from unittest.mock import patch

import anyio
import pytest

from mcp.shared.session import BaseSession
from mcp.types import (
    ClientRequest,
    EmptyResult,
    PingRequest,
)


@pytest.mark.anyio
async def test_send_request_stream_cleanup():
    """
    Test that send_request properly cleans up streams when an exception occurs.

    This test mocks out most of the session functionality to focus on stream cleanup.
    """

    # Create a mock session with the minimal required functionality
    class TestSession(BaseSession):
        async def _send_response(self, request_id, response):
            pass

    # Create streams
    write_stream_send, write_stream_receive = anyio.create_memory_object_stream(1)
    read_stream_send, read_stream_receive = anyio.create_memory_object_stream(1)

    # Create the session
    session = TestSession(
        read_stream_receive,
        write_stream_send,
        object,  # Request type doesn't matter for this test
        object,  # Notification type doesn't matter for this test
    )

    # Create a test request
    request = ClientRequest(
        PingRequest(
            method="ping",
        )
    )

    # Patch the _write_stream.send method to raise an exception
    async def mock_send(*args, **kwargs):
        raise RuntimeError("Simulated network error")

    # Record the response streams before the test
    initial_stream_count = len(session._response_streams)

    # Run the test with the patched method
    with patch.object(session._write_stream, "send", mock_send):
        with pytest.raises(RuntimeError):
            await session.send_request(request, EmptyResult)

    # Verify that no response streams were leaked
    assert len(session._response_streams) == initial_stream_count, (
        f"Expected {initial_stream_count} response streams after request, "
        f"but found {len(session._response_streams)}"
    )

    # Clean up
    await write_stream_send.aclose()
    await write_stream_receive.aclose()
    await read_stream_send.aclose()
    await read_stream_receive.aclose()
