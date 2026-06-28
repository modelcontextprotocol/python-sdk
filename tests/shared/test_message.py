"""Tests for the transport-facing helpers in `mcp.shared.message`."""

import anyio
import pytest
from mcp_types import JSONRPCNotification

from mcp.shared.message import RequestSettled, SessionMessage, wire_messages


@pytest.mark.anyio
async def test_wire_messages_strips_settled_markers_and_preserves_frame_order():
    """`wire_messages` yields only serializable frames: `RequestSettled` markers are dropped (they
    must never reach any wire) and the surviving frames keep their order."""
    send, receive = anyio.create_memory_object_stream[SessionMessage | RequestSettled](3)
    first = SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/first"))
    last = SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/last"))
    send.send_nowait(first)
    send.send_nowait(RequestSettled(request_id=1))
    send.send_nowait(last)
    send.close()

    with anyio.fail_after(5):
        assert [frame async for frame in wire_messages(receive)] == [first, last]
    receive.close()
