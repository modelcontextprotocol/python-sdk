"""Tests for the no-back-channel path (stateless HTTP).

A `Connection.from_envelope(...)` connection installs the no-channel sentinel
as its standalone outbound, so server-to-client requests with no related
request to ride on raise `NoBackChannelError` from the channel itself.

See: https://github.com/modelcontextprotocol/python-sdk/issues/1097
"""

from collections.abc import Mapping
from typing import Any

import mcp_types as types
import pytest
from mcp_types import LATEST_PROTOCOL_VERSION

from mcp.server.connection import Connection
from mcp.server.session import ServerSession
from mcp.shared.dispatcher import CallOptions
from mcp.shared.exceptions import NoBackChannelError


class StubOutbound:
    """Records `send_raw_request` / `notify` calls and returns a canned result.

    Structurally a `DispatchContext[Any]` so it can stand in for the per-request channel.
    """

    transport: Any = None
    can_send_request: bool = True
    request_id: Any = None
    message_metadata: Any = None
    cancel_requested: Any = None

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.requests: list[tuple[str, Mapping[str, Any] | None, CallOptions | None]] = []
        self.notifications: list[tuple[str, Mapping[str, Any] | None]] = []
        self.result = result if result is not None else {}

    async def send_raw_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
    ) -> dict[str, Any]:
        self.requests.append((method, params, opts))
        return self.result

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        self.notifications.append((method, params))

    async def progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        raise NotImplementedError  # pragma: no cover


def _no_channel_session(request_ch: StubOutbound | None = None) -> tuple[ServerSession, StubOutbound]:
    """A session whose standalone channel is the connection's no-channel
    sentinel; the request channel is a working stub."""
    conn = Connection.from_envelope(LATEST_PROTOCOL_VERSION, None, None)
    assert conn.has_standalone_channel is False
    request = request_ch if request_ch is not None else StubOutbound()
    return ServerSession(request, conn), request


@pytest.fixture
def no_channel_session() -> ServerSession:
    session, _ = _no_channel_session()
    return session


@pytest.mark.anyio
async def test_list_roots_raises_no_back_channel(no_channel_session: ServerSession):
    """SDK-defined: `list_roots` has no `related_request_id` so it always rides
    the standalone channel, which raises here."""
    with pytest.raises(NoBackChannelError) as exc:
        await no_channel_session.list_roots()  # pyright: ignore[reportDeprecated]
    assert exc.value.method == "roots/list"


@pytest.mark.anyio
async def test_send_ping_raises_no_back_channel(no_channel_session: ServerSession):
    """SDK-defined: `send_ping` rides the standalone channel and raises when there is none."""
    with pytest.raises(NoBackChannelError) as exc:
        await no_channel_session.send_ping()
    assert exc.value.method == "ping"


@pytest.mark.anyio
async def test_create_message_raises_no_back_channel_without_related_id(no_channel_session: ServerSession):
    """SDK-defined: `create_message` without a related id rides the standalone channel and raises."""
    with pytest.raises(NoBackChannelError) as exc:
        await no_channel_session.create_message(  # pyright: ignore[reportDeprecated]
            messages=[types.SamplingMessage(role="user", content=types.TextContent(type="text", text="hi"))],
            max_tokens=100,
        )
    assert exc.value.method == "sampling/createMessage"


@pytest.mark.anyio
async def test_elicit_form_raises_no_back_channel_without_related_id(no_channel_session: ServerSession):
    """SDK-defined: `elicit_form` without a related id rides the standalone channel and raises."""
    with pytest.raises(NoBackChannelError) as exc:
        await no_channel_session.elicit_form(message="m", requested_schema=types.ElicitRequestedSchema(properties={}))
    assert exc.value.method == "elicitation/create"


@pytest.mark.anyio
async def test_elicit_url_raises_no_back_channel_without_related_id(no_channel_session: ServerSession):
    """SDK-defined: `elicit_url` without a related id rides the standalone channel and raises."""
    with pytest.raises(NoBackChannelError) as exc:
        await no_channel_session.elicit_url(message="m", url="https://example.com/auth", elicitation_id="e-1")
    assert exc.value.method == "elicitation/create"


@pytest.mark.anyio
async def test_elicit_deprecated_raises_no_back_channel_without_related_id(no_channel_session: ServerSession):
    """SDK-defined: the deprecated `elicit` alias routes the same as `elicit_form` and raises."""
    with pytest.raises(NoBackChannelError) as exc:
        await no_channel_session.elicit(message="m", requested_schema=types.ElicitRequestedSchema(properties={}))
    assert exc.value.method == "elicitation/create"


@pytest.mark.anyio
async def test_send_request_raises_no_back_channel_without_related_id(no_channel_session: ServerSession):
    """SDK-defined: the generic `send_request` path with no metadata routes standalone and raises."""
    with pytest.raises(NoBackChannelError) as exc:
        await no_channel_session.send_request(types.ListRootsRequest(), types.ListRootsResult)
    assert exc.value.method == "roots/list"


@pytest.mark.anyio
async def test_elicit_form_with_related_id_rides_the_request_channel():
    """SDK-defined: with a related request the message rides the per-request
    channel, so the no-channel standalone is never touched and the call succeeds."""
    session, request_ch = _no_channel_session(StubOutbound(result={"action": "cancel"}))
    result = await session.elicit_form(
        message="m", requested_schema=types.ElicitRequestedSchema(properties={}), related_request_id=3
    )
    assert isinstance(result, types.ElicitResult)
    assert request_ch.requests[0][0] == "elicitation/create"


@pytest.mark.anyio
async def test_send_log_message_with_related_id_rides_the_request_channel():
    """SDK-defined: the deprecated ``send_log_message`` notification with a related id
    rides the per-request channel, so it is delivered even with no standalone back-channel."""
    session, request_ch = _no_channel_session()
    await session.send_log_message(  # pyright: ignore[reportDeprecated]
        level="info", data="hello", logger="test", related_request_id=3
    )
    assert request_ch.notifications == [("notifications/message", {"level": "info", "data": "hello", "logger": "test"})]


@pytest.mark.anyio
async def test_unrelated_notification_is_dropped_silently():
    """SDK-defined: notifications on the no-channel standalone are best-effort — dropped, never raised."""
    session, request_ch = _no_channel_session()
    await session.send_tool_list_changed()
    assert request_ch.notifications == []


@pytest.mark.anyio
async def test_loop_connection_outbound_does_not_raise_no_back_channel():
    """SDK-defined: a `for_loop` connection holds a real outbound, so the
    standalone path reaches the channel rather than raising."""
    standalone = StubOutbound(result={"roots": []})
    conn = Connection.for_loop(standalone)
    assert conn.has_standalone_channel is True
    session = ServerSession(StubOutbound(), conn)
    result = await session.list_roots()  # pyright: ignore[reportDeprecated]
    assert isinstance(result, types.ListRootsResult)
    assert standalone.requests[0][0] == "roots/list"


@pytest.mark.anyio
async def test_from_envelope_connection_ping_raises_no_back_channel():
    """SDK-defined: `Connection`'s own helpers route through the same sentinel,
    so `ping` on a `from_envelope` connection raises."""
    conn = Connection.from_envelope(LATEST_PROTOCOL_VERSION, None, None)
    with pytest.raises(NoBackChannelError) as exc:
        await conn.ping()
    assert exc.value.method == "ping"
