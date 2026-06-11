"""Tests for the contextvars-carrying memory-stream wrappers."""

import anyio
import pytest

from mcp.shared._context_streams import create_context_streams

pytestmark = pytest.mark.anyio


async def test_sync_close_closes_the_underlying_streams() -> None:
    """The wrappers mirror anyio's memory streams: close() is the sync form of aclose()."""
    send, receive = create_context_streams[str](1)
    await send.send("queued")
    send.close()
    receive.close()
    with pytest.raises(anyio.ClosedResourceError):
        await send.send("after close")
    with pytest.raises(anyio.ClosedResourceError):
        await receive.receive()
