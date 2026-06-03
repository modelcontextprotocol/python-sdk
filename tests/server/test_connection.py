"""Tests for `Connection`.

`Connection` wraps an `Outbound` (the standalone stream). Its `notify` is
best-effort (never raises); `send_raw_request` is gated on
`has_standalone_channel`. Tested with a stub `Outbound` so we can assert wire
shape and inject failures.
"""

import logging
from collections.abc import Mapping
from typing import Any

import anyio
import pytest

from mcp.server.connection import Connection
from mcp.shared.dispatcher import CallOptions
from mcp.shared.exceptions import NoBackChannelError
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    ClientCapabilities,
    CreateMessageRequest,
    CreateMessageRequestParams,
    ElicitationCapability,
    EmptyResult,
    Implementation,
    InitializeRequestParams,
    ListRootsRequest,
    ListRootsResult,
    PingRequest,
    RootsCapability,
    SamplingCapability,
    SamplingContextCapability,
    SamplingToolsCapability,
)


def _client_params(capabilities: ClientCapabilities) -> InitializeRequestParams:
    return InitializeRequestParams(
        protocol_version=LATEST_PROTOCOL_VERSION,
        capabilities=capabilities,
        client_info=Implementation(name="t", version="0"),
    )


class StubOutbound:
    def __init__(
        self, *, result: dict[str, Any] | None = None, raise_on_send: type[BaseException] | None = None
    ) -> None:
        self.requests: list[tuple[str, Mapping[str, Any] | None]] = []
        self.notifications: list[tuple[str, Mapping[str, Any] | None]] = []
        self._result = result if result is not None else {}
        self._raise_on_send = raise_on_send

    async def send_raw_request(
        self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None
    ) -> dict[str, Any]:
        self.requests.append((method, params))
        return self._result

    async def notify(self, method: str, params: Mapping[str, Any] | None) -> None:
        if self._raise_on_send is not None:
            raise self._raise_on_send()
        self.notifications.append((method, params))


@pytest.mark.anyio
async def test_connection_notify_forwards_to_outbound():
    out = StubOutbound()
    conn = Connection(out, has_standalone_channel=True)
    await conn.notify("notifications/message", {"level": "info", "data": "hi"})
    assert out.notifications == [("notifications/message", {"level": "info", "data": "hi"})]


@pytest.mark.anyio
async def test_connection_notify_swallows_broken_stream_and_debug_logs(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG, logger="mcp.server.connection")
    out = StubOutbound(raise_on_send=anyio.BrokenResourceError)
    conn = Connection(out, has_standalone_channel=True)
    await conn.notify("notifications/message", {"data": "x"})  # must not raise
    assert "stream closed" in caplog.text.lower()


@pytest.mark.anyio
async def test_connection_notify_drops_when_no_standalone_channel(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG, logger="mcp.server.connection")
    out = StubOutbound()
    conn = Connection(out, has_standalone_channel=False)
    await conn.notify("notifications/message", {"data": "x"})  # must not raise
    assert out.notifications == []
    assert "no standalone channel" in caplog.text.lower()


@pytest.mark.anyio
async def test_connection_send_raw_request_raises_nobackchannel_when_no_standalone_channel():
    conn = Connection(StubOutbound(), has_standalone_channel=False)
    with pytest.raises(NoBackChannelError):
        await conn.send_raw_request("ping", None)


@pytest.mark.anyio
async def test_connection_send_raw_request_forwards_when_standalone_channel_present():
    out = StubOutbound()
    conn = Connection(out, has_standalone_channel=True)
    result = await conn.send_raw_request("ping", None)
    assert out.requests == [("ping", None)]
    assert result == {}


@pytest.mark.anyio
async def test_connection_send_request_with_spec_type_infers_result_type():
    out = StubOutbound(result={"roots": [{"uri": "file:///ws"}]})
    conn = Connection(out, has_standalone_channel=True)
    result = await conn.send_request(ListRootsRequest())
    method, _ = out.requests[0]
    assert method == "roots/list"
    assert isinstance(result, ListRootsResult)
    assert str(result.roots[0].uri) == "file:///ws"


@pytest.mark.anyio
async def test_connection_send_request_validates_result_alias_only():
    """Peer results validate alias-only; a snake_case key from the wire is
    ignored as extra, not populated by Python field name."""
    snake = {"role": "assistant", "content": {"type": "text", "text": "x"}, "model": "m", "stop_reason": "endTurn"}
    conn = Connection(StubOutbound(result=snake), has_standalone_channel=True)
    result = await conn.send_request(CreateMessageRequest(params=CreateMessageRequestParams(messages=[], max_tokens=1)))
    assert result.stop_reason is None


@pytest.mark.anyio
async def test_connection_send_request_with_result_type_kwarg_validates_custom_type():
    out = StubOutbound(result={})
    conn = Connection(out, has_standalone_channel=True)
    result = await conn.send_request(PingRequest(), result_type=EmptyResult)
    assert isinstance(result, EmptyResult)


@pytest.mark.anyio
async def test_connection_ping_sends_ping_on_standalone():
    out = StubOutbound()
    conn = Connection(out, has_standalone_channel=True)
    await conn.ping()
    assert out.requests == [("ping", None)]


@pytest.mark.anyio
async def test_connection_log_sends_logging_message_notification():
    out = StubOutbound()
    conn = Connection(out, has_standalone_channel=True)
    await conn.log("info", {"k": "v"}, logger="my.logger")
    method, params = out.notifications[0]
    assert method == "notifications/message"
    assert params is not None
    assert params["level"] == "info"
    assert params["data"] == {"k": "v"}
    assert params["logger"] == "my.logger"


@pytest.mark.anyio
async def test_connection_log_with_meta_includes_meta_in_params():
    out = StubOutbound()
    conn = Connection(out, has_standalone_channel=True)
    await conn.log("info", "x", meta={"traceId": "abc"})
    _, params = out.notifications[0]
    assert params is not None
    assert params["_meta"] == {"traceId": "abc"}


@pytest.mark.anyio
async def test_connection_list_changed_notifications_send_correct_methods():
    out = StubOutbound()
    conn = Connection(out, has_standalone_channel=True)
    await conn.send_tool_list_changed()
    await conn.send_prompt_list_changed()
    await conn.send_resource_list_changed()
    await conn.send_resource_updated("file:///workspace/a.txt")
    methods = [m for m, _ in out.notifications]
    assert methods == [
        "notifications/tools/list_changed",
        "notifications/prompts/list_changed",
        "notifications/resources/list_changed",
        "notifications/resources/updated",
    ]
    assert out.notifications[-1][1] == {"uri": "file:///workspace/a.txt"}


@pytest.mark.anyio
async def test_connection_send_tool_list_changed_with_meta_includes_meta_only_params():
    out = StubOutbound()
    conn = Connection(out, has_standalone_channel=True)
    await conn.send_tool_list_changed(meta={"k": 1})
    assert out.notifications == [("notifications/tools/list_changed", {"_meta": {"k": 1}})]


def test_connection_check_capability_false_before_initialized():
    conn = Connection(StubOutbound(), has_standalone_channel=True)
    assert conn.check_capability(ClientCapabilities(sampling=SamplingCapability())) is False


@pytest.mark.parametrize(
    ("have", "want", "expected"),
    [
        (ClientCapabilities(roots=None), ClientCapabilities(roots=RootsCapability()), False),
        (
            ClientCapabilities(roots=RootsCapability(list_changed=False)),
            ClientCapabilities(roots=RootsCapability(list_changed=True)),
            False,
        ),
        (ClientCapabilities(sampling=None), ClientCapabilities(sampling=SamplingCapability()), False),
        (
            ClientCapabilities(sampling=SamplingCapability()),
            ClientCapabilities(sampling=SamplingCapability(context=SamplingContextCapability())),
            False,
        ),
        (
            ClientCapabilities(sampling=SamplingCapability()),
            ClientCapabilities(sampling=SamplingCapability(tools=SamplingToolsCapability())),
            False,
        ),
        (
            ClientCapabilities(sampling=SamplingCapability(tools=SamplingToolsCapability())),
            ClientCapabilities(sampling=SamplingCapability(tools=SamplingToolsCapability())),
            True,
        ),
        (ClientCapabilities(experimental=None), ClientCapabilities(experimental={"a": {}}), False),
        (ClientCapabilities(experimental={"a": {}}), ClientCapabilities(experimental={"b": {}}), False),
        (ClientCapabilities(experimental={"a": {"x": 1}}), ClientCapabilities(experimental={"a": {"x": 2}}), False),
        (ClientCapabilities(experimental={"a": {}}), ClientCapabilities(experimental={"a": {}}), True),
    ],
)
def test_check_capability_per_field_branches(have: ClientCapabilities, want: ClientCapabilities, expected: bool):
    conn = Connection(StubOutbound(), has_standalone_channel=True)
    conn.client_params = _client_params(have)
    assert conn.check_capability(want) is expected


def test_connection_client_info_and_capabilities_derive_from_client_params():
    conn = Connection(StubOutbound(), has_standalone_channel=True)
    assert conn.client_info is None
    assert conn.client_capabilities is None
    caps = ClientCapabilities(sampling=SamplingCapability())
    conn.client_params = _client_params(caps)
    assert conn.client_info is not None and conn.client_info.name == "t"
    assert conn.client_capabilities == caps


def test_connection_check_capability_true_when_client_declares_it():
    conn = Connection(StubOutbound(), has_standalone_channel=True)
    conn.client_params = _client_params(
        ClientCapabilities(sampling=SamplingCapability(), roots=RootsCapability(list_changed=True))
    )
    conn.initialized.set()
    assert conn.check_capability(ClientCapabilities(sampling=SamplingCapability())) is True
    assert conn.check_capability(ClientCapabilities(roots=RootsCapability(list_changed=True))) is True
    assert conn.check_capability(ClientCapabilities(elicitation=ElicitationCapability())) is False
