"""Wire-level invariants observed at the client's transport boundary.

These behaviours are invisible to API callers -- they are properties of the raw JSON-RPC frames.
The tests wrap the in-memory transport in a RecordingTransport, which tees every message crossing
the transport seam into a list without touching the session, so the assertions hold for whatever
the session implementation sends rather than for what its API returns.
"""

import anyio
import pytest
from inline_snapshot import snapshot

from mcp import types
from mcp.client._memory import InMemoryTransport
from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.shared.message import SessionMessage
from mcp.types import CallToolResult, JSONRPCNotification, JSONRPCRequest, JSONRPCResponse, TextContent
from tests.interaction._helpers import RecordingTransport, _RecordingReadStream
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


def _echo_server() -> Server:
    """A server with one echo tool, used by every test in this module."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="echo", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "echo"
        return CallToolResult(content=[TextContent(text="ok")])

    return Server("wire", on_list_tools=list_tools, on_call_tool=call_tool)


@requirement("protocol:request-id:unique")
async def test_request_ids_are_unique_and_never_null() -> None:
    """Every request the client sends carries a distinct, non-null id.

    The id sequence is pinned: sequential integers from zero, in send order, including the
    schema-cache refresh the client performs after the first successful tool call.
    """
    recording = RecordingTransport(InMemoryTransport(_echo_server()))

    async with Client(recording) as client:
        await client.list_tools()
        await client.call_tool("echo", {})
        await client.call_tool("echo", {})
        await client.send_ping()

    sent = [message.message for message in recording.sent]
    request_ids = [message.id for message in sent if isinstance(message, JSONRPCRequest)]
    assert all(request_id is not None for request_id in request_ids)
    assert len(request_ids) == len(set(request_ids))
    # initialize, tools/list, tools/call, tools/call, ping -- the client does not issue a
    # schema-cache refresh here because the explicit tools/list already populated the cache.
    assert request_ids == snapshot([0, 1, 2, 3, 4])


@requirement("protocol:notifications:no-response")
async def test_notifications_are_never_answered() -> None:
    """A notification produces no response: everything the server sends back answers a request.

    The client sends two notifications (initialized and roots/list_changed) and several requests;
    the messages received from the server must be exactly one response per request, each carrying
    the id of the request it answers, and nothing else.
    """
    recording = RecordingTransport(InMemoryTransport(_echo_server()))

    async with Client(recording) as client:
        await client.send_roots_list_changed()
        await client.send_ping()

    sent = [message.message for message in recording.sent]
    sent_request_ids = [message.id for message in sent if isinstance(message, JSONRPCRequest)]
    sent_notifications = [message for message in sent if isinstance(message, JSONRPCNotification)]
    received = [message.message for message in recording.received if isinstance(message, SessionMessage)]
    received_responses = [message for message in received if isinstance(message, JSONRPCResponse)]

    assert len(sent_notifications) == 2  # notifications/initialized and notifications/roots/list_changed
    assert len(received_responses) == len(received)  # nothing the server sent was anything but a response
    assert [message.id for message in received_responses] == sent_request_ids


async def test_recording_read_stream_ends_iteration_when_the_sender_closes() -> None:
    """The recording wrapper preserves the end-of-stream behaviour of the stream it wraps.

    This exercises the helper itself rather than an interaction-model behaviour: a transport whose
    far end closes must end the client's receive loop cleanly, and the wrapper must not swallow or
    mistranslate that.
    """
    send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    log: list[SessionMessage | Exception] = []
    async with send_stream, _RecordingReadStream(receive_stream, log) as wrapped:
        await send_stream.aclose()
        items = [item async for item in wrapped]
    assert items == []
    assert log == []


@requirement("lifecycle:initialized-notification")
async def test_exactly_one_initialized_notification_is_sent_after_the_handshake() -> None:
    """The client sends initialized exactly once, between the initialize response and its first request.

    The full method sequence the client puts on the wire is pinned in send order.
    """
    recording = RecordingTransport(InMemoryTransport(_echo_server()))

    async with Client(recording) as client:
        await client.list_tools()

    sent_methods = [
        message.message.method
        for message in recording.sent
        if isinstance(message.message, JSONRPCRequest | JSONRPCNotification)
    ]
    assert sent_methods.count("notifications/initialized") == 1
    assert sent_methods == snapshot(["initialize", "notifications/initialized", "tools/list"])
