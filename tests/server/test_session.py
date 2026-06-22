"""Tests for `ServerSession`.

`ServerSession` is a thin per-request proxy over two `Outbound` channels and a
`Connection`. Tested with stub outbounds so we can assert what reaches the wire
(method, params, `CallOptions`) and which channel it routed to, without standing
up a transport.
"""

from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import ValidationError

from mcp import types
from mcp.server.connection import Connection
from mcp.server.session import ServerSession
from mcp.shared.dispatcher import CallOptions, Outbound
from mcp.shared.message import ServerMessageMetadata
from mcp.shared.version import MODERN_PROTOCOL_VERSIONS
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    ClientCapabilities,
    Implementation,
    SamplingCapability,
    SamplingToolsCapability,
)


class StubOutbound:
    """Records `send_raw_request` / `notify` calls and returns a canned result."""

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


def _make_session(
    outbound: StubOutbound,
    *,
    capabilities: ClientCapabilities | None = None,
    protocol_version: str = LATEST_PROTOCOL_VERSION,
) -> ServerSession:
    """Single-channel session: the stub is both request and standalone outbound."""
    client_info = Implementation(name="c", version="0") if capabilities is not None else None
    conn = Connection.from_envelope(protocol_version, client_info, capabilities, outbound=outbound)
    return ServerSession(outbound, conn)


def _two_channel_session(request_ch: Outbound, standalone_ch: Outbound) -> ServerSession:
    """Distinct request/standalone outbounds so routing assertions can tell the channels apart."""
    conn = Connection.from_envelope(LATEST_PROTOCOL_VERSION, None, None, outbound=standalone_ch)
    return ServerSession(request_ch, conn)


@pytest.mark.anyio
async def test_send_request_forwards_timeout_and_progress_callback_as_call_options():
    outbound = StubOutbound(result={"roots": []})
    session = _make_session(outbound)

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        raise NotImplementedError

    result = await session.send_request(
        types.ListRootsRequest(),
        types.ListRootsResult,
        request_read_timeout_seconds=2.5,
        progress_callback=on_progress,
    )
    assert isinstance(result, types.ListRootsResult)
    method, _params, opts = outbound.requests[0]
    assert method == "roots/list"
    assert opts == {"timeout": 2.5, "on_progress": on_progress}


@pytest.mark.anyio
async def test_send_request_omits_call_options_when_none_given():
    outbound = StubOutbound(result={"roots": []})
    session = _make_session(outbound)
    await session.send_request(types.ListRootsRequest(), types.ListRootsResult)
    _method, _params, opts = outbound.requests[0]
    assert opts is None


@pytest.mark.anyio
async def test_send_request_timeout_zero_is_forwarded():
    """0 is a real timeout (fail at the first checkpoint, `anyio.fail_after(0)`
    semantics) and must reach the channel; only `None` means "no timeout"."""
    outbound = StubOutbound(result={})
    session = _make_session(outbound)
    await session.send_request(types.PingRequest(), types.EmptyResult, request_read_timeout_seconds=0.0)
    assert outbound.requests[0][2] == {"timeout": 0.0}


@pytest.mark.anyio
async def test_send_request_without_related_id_routes_to_standalone_channel():
    """SDK-defined: no `related_request_id` routes the request onto the connection's standalone channel."""
    request_ch = StubOutbound()
    standalone_ch = StubOutbound(result={"roots": []})
    session = _two_channel_session(request_ch, standalone_ch)
    await session.send_request(types.ListRootsRequest(), types.ListRootsResult)
    assert request_ch.requests == []
    assert standalone_ch.requests[0][0] == "roots/list"


@pytest.mark.anyio
async def test_send_request_with_related_id_routes_to_request_channel():
    """SDK-defined: with `related_request_id` the request rides the per-request channel
    (the originating POST's response stream over streamable HTTP)."""
    request_ch = StubOutbound(result={"action": "cancel"})
    standalone_ch = StubOutbound()
    session = _two_channel_session(request_ch, standalone_ch)
    result = await session.send_request(
        types.ElicitRequest(params=types.ElicitRequestFormParams(message="q", requested_schema={})),
        types.ElicitResult,
        metadata=ServerMessageMetadata(related_request_id=7),
    )
    assert isinstance(result, types.ElicitResult)
    assert standalone_ch.requests == []
    assert request_ch.requests[0][0] == "elicitation/create"


@pytest.mark.anyio
async def test_send_notification_routes_by_related_request_id():
    """SDK-defined: notifications select channel by `related_request_id` exactly like requests."""
    request_ch = StubOutbound()
    standalone_ch = StubOutbound()
    session = _two_channel_session(request_ch, standalone_ch)
    await session.send_tool_list_changed()
    await session.send_progress_notification("tok", 0.5, related_request_id="req-1")
    assert [m for m, _ in standalone_ch.notifications] == ["notifications/tools/list_changed"]
    assert [m for m, _ in request_ch.notifications] == ["notifications/progress"]


@pytest.mark.anyio
async def test_send_request_validates_the_client_result_against_the_surface_schema():
    """A spec-method result that fails the per-version surface schema raises
    `ValidationError` even when the caller's `result_type` would accept it."""
    session = _make_session(StubOutbound(result={"roots": "nope"}))
    with pytest.raises(ValidationError):
        await session.send_request(types.ListRootsRequest(), types.EmptyResult)


@pytest.mark.anyio
async def test_send_request_passes_a_spec_valid_client_result():
    """A spec-valid client result passes the surface gate and parses to the typed model."""
    session = _make_session(StubOutbound(result={"roots": [{"uri": "file:///ws"}]}))
    result = await session.send_request(types.ListRootsRequest(), types.ListRootsResult)
    assert isinstance(result, types.ListRootsResult)
    assert str(result.roots[0].uri) == "file:///ws"


@pytest.mark.anyio
async def test_send_request_skips_the_surface_gate_when_method_absent_at_version():
    """Surface row absent for the connection's version: gate is bypassed and only
    `result_type` validates."""
    session = _make_session(StubOutbound(result={}), protocol_version=MODERN_PROTOCOL_VERSIONS[0])
    result = await session.send_request(types.PingRequest(), types.EmptyResult)
    assert isinstance(result, types.EmptyResult)


@pytest.mark.anyio
async def test_send_request_validates_result_alias_only():
    """Peer results validate alias-only; a snake_case key from the wire is
    ignored as extra, not populated by Python field name."""
    snake = {"role": "assistant", "content": {"type": "text", "text": "x"}, "model": "m", "stop_reason": "endTurn"}
    session = _make_session(StubOutbound(result=snake))
    request = types.CreateMessageRequest(params=types.CreateMessageRequestParams(messages=[], max_tokens=1))
    result = await session.send_request(request, types.CreateMessageResult)
    assert result.stop_reason is None


@pytest.mark.anyio
async def test_create_message_with_tools_returns_with_tools_result():
    outbound = StubOutbound(result={"role": "assistant", "content": [{"type": "text", "text": "ok"}], "model": "m"})
    session = _make_session(
        outbound, capabilities=ClientCapabilities(sampling=SamplingCapability(tools=SamplingToolsCapability()))
    )
    result = await session.create_message(  # pyright: ignore[reportDeprecated]
        messages=[types.SamplingMessage(role="user", content=types.TextContent(type="text", text="hi"))],
        max_tokens=10,
        tools=[types.Tool(name="t", input_schema={"type": "object"})],
    )
    assert isinstance(result, types.CreateMessageResultWithTools)
    method, params, _opts = outbound.requests[0]
    assert method == "sampling/createMessage"
    assert params is not None and params["tools"][0]["name"] == "t"


def test_check_client_capability_delegates_to_connection():
    outbound = StubOutbound()
    session = _make_session(outbound, capabilities=ClientCapabilities(sampling=SamplingCapability()))
    assert session.check_client_capability(ClientCapabilities(sampling=SamplingCapability())) is True
    assert session.check_client_capability(ClientCapabilities(experimental={"x": {}})) is False


def test_protocol_version_proxies_connection():
    """SDK-defined: `session.protocol_version` reads through to the held `Connection`."""
    _ARBITRARY_VERSION = "sentinel-version"  # identity-only: any string the connection holds
    conn = Connection.from_envelope(_ARBITRARY_VERSION, None, None)
    session = ServerSession(StubOutbound(), conn)
    assert session.protocol_version == _ARBITRARY_VERSION
    assert session.client_params is None
