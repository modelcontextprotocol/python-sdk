"""Tests for the no-back-channel path (stateless HTTP).

A `Connection.from_envelope(...)` connection installs the no-channel sentinel
as its standalone outbound, so server-to-client requests with no related
request to ride on raise `NoBackChannelError` from the channel itself — no
mode flag, no per-method guard.

See: https://github.com/modelcontextprotocol/python-sdk/issues/1097
"""

import pytest

from mcp import types
from mcp.server.connection import Connection
from mcp.server.session import ServerSession
from mcp.shared.exceptions import NoBackChannelError
from mcp.types import LATEST_PROTOCOL_VERSION

from .test_session import StubOutbound


def _no_channel_session(request_ch: StubOutbound | None = None) -> tuple[ServerSession, StubOutbound]:
    """A session whose standalone channel is the connection's no-channel
    sentinel; the request channel is a working stub."""
    conn = Connection.from_envelope(LATEST_PROTOCOL_VERSION, None, None)
    assert conn.has_standalone_channel is False
    request = request_ch if request_ch is not None else StubOutbound()
    return ServerSession(request, conn, standalone_outbound=conn.outbound), request


@pytest.fixture
def no_channel_session() -> ServerSession:
    session, _ = _no_channel_session()
    return session


@pytest.mark.anyio
async def test_list_roots_raises_no_back_channel(no_channel_session: ServerSession):
    """`list_roots` has no `related_request_id` so it always rides the
    standalone channel, which structurally raises here."""
    with pytest.raises(NoBackChannelError, match="roots/list"):
        await no_channel_session.list_roots()


@pytest.mark.anyio
async def test_send_ping_raises_no_back_channel(no_channel_session: ServerSession):
    with pytest.raises(NoBackChannelError, match="ping"):
        await no_channel_session.send_ping()


@pytest.mark.anyio
async def test_create_message_raises_no_back_channel_without_related_id(no_channel_session: ServerSession):
    with pytest.raises(NoBackChannelError, match="sampling/createMessage"):
        await no_channel_session.create_message(
            messages=[types.SamplingMessage(role="user", content=types.TextContent(type="text", text="hi"))],
            max_tokens=100,
        )


@pytest.mark.anyio
async def test_elicit_form_raises_no_back_channel_without_related_id(no_channel_session: ServerSession):
    with pytest.raises(NoBackChannelError, match="elicitation/create"):
        await no_channel_session.elicit_form(message="m", requested_schema={"type": "object", "properties": {}})


@pytest.mark.anyio
async def test_elicit_url_raises_no_back_channel_without_related_id(no_channel_session: ServerSession):
    with pytest.raises(NoBackChannelError, match="elicitation/create"):
        await no_channel_session.elicit_url(message="m", url="https://example.com/auth", elicitation_id="e-1")


@pytest.mark.anyio
async def test_elicit_deprecated_raises_no_back_channel_without_related_id(no_channel_session: ServerSession):
    with pytest.raises(NoBackChannelError, match="elicitation/create"):
        await no_channel_session.elicit(message="m", requested_schema={"type": "object", "properties": {}})


@pytest.mark.anyio
async def test_send_request_raises_no_back_channel_without_related_id(no_channel_session: ServerSession):
    """The generic `send_request` path: no metadata → standalone → raise."""
    with pytest.raises(NoBackChannelError, match="roots/list"):
        await no_channel_session.send_request(types.ListRootsRequest(), types.ListRootsResult)


@pytest.mark.anyio
async def test_elicit_form_with_related_id_rides_the_request_channel():
    """With a related request the message rides the per-request channel, so the
    no-channel standalone is never touched and the call succeeds."""
    session, request_ch = _no_channel_session(StubOutbound(result={"action": "cancel"}))
    result = await session.elicit_form(
        message="m", requested_schema={"type": "object", "properties": {}}, related_request_id=3
    )
    assert isinstance(result, types.ElicitResult)
    assert request_ch.requests[0][0] == "elicitation/create"


@pytest.mark.anyio
async def test_unrelated_notification_is_dropped_silently():
    """Notifications on the no-channel standalone are best-effort: dropped, never raised."""
    session, request_ch = _no_channel_session()
    await session.send_tool_list_changed()
    assert request_ch.notifications == []


@pytest.mark.anyio
async def test_loop_connection_outbound_does_not_raise_no_back_channel():
    """A `for_loop` connection holds a real outbound, so the standalone path
    reaches the channel rather than raising."""
    standalone = StubOutbound(result={"roots": []})
    conn = Connection.for_loop(standalone)
    assert conn.has_standalone_channel is True
    session = ServerSession(StubOutbound(), conn, standalone_outbound=conn.outbound)
    result = await session.list_roots()
    assert isinstance(result, types.ListRootsResult)
    assert standalone.requests[0][0] == "roots/list"


@pytest.mark.anyio
async def test_from_envelope_connection_ping_raises_no_back_channel():
    """`Connection`'s own helpers route through the same sentinel: `ping`
    on a `from_envelope` connection raises structurally."""
    conn = Connection.from_envelope(LATEST_PROTOCOL_VERSION, None, None)
    with pytest.raises(NoBackChannelError):
        await conn.ping()
