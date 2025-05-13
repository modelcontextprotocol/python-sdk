import asyncio
from uuid import UUID

import pytest
from starlette.types import Message, Scope

from mcp.server.sse import SseServerTransport


@pytest.mark.anyio
async def test_sse_disconnect_handle():
    transport = SseServerTransport(endpoint="/sse")
    # Create a minimal ASGI scope for an HTTP GET request
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/sse",
        "headers": [],
    }
    send_disconnect = False

    # Dummy receive and send functions
    async def receive() -> dict:
        nonlocal send_disconnect
        if not send_disconnect:
            send_disconnect = True
            return {"type": "http.request"}
        else:
            return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        await asyncio.sleep(0)

    # Run the connect_sse context manager
    async with transport.connect_sse(scope, receive, send) as (
        read_stream,
        write_stream,
    ):
        # Assert that streams are provided
        assert read_stream is not None
        assert write_stream is not None

        # There should be exactly one session
        assert len(transport._read_stream_writers) == 1
        # Check that the session key is a UUID
        session_id = next(iter(transport._read_stream_writers.keys()))
        assert isinstance(session_id, UUID)

    # Check that the session_id should be clean up
    assert session_id not in transport._read_stream_writers

    # After context exits, session should be cleaned up
    assert len(transport._read_stream_writers) == 0
