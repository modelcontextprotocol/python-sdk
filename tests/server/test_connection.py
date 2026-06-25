"""Tests for `Connection`.

`Connection` wraps an `Outbound` (the standalone stream). Construct it via the
`from_envelope` / `for_loop` factories so `protocol_version` is always
populated and `has_standalone_channel` is derived from the held outbound. Its
`notify` is best-effort (never raises); `send_raw_request` raises
`NoBackChannelError` structurally from the no-channel sentinel. Tested with a
stub `Outbound` so we can assert wire shape and inject failures.
"""

import logging
from collections.abc import Mapping
from typing import Any, Literal

import anyio
import pytest
from pydantic import BaseModel, ValidationError

from mcp.server.connection import Connection
from mcp.shared.dispatcher import CallOptions
from mcp.shared.exceptions import NoBackChannelError
from mcp.shared.version import MODERN_PROTOCOL_VERSIONS
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    ClientCapabilities,
    CreateMessageRequest,
    CreateMessageRequestParams,
    ElicitationCapability,
    EmptyResult,
    FormElicitationCapability,
    Implementation,
    ListRootsRequest,
    ListRootsResult,
    PingRequest,
    Request,
    RequestParams,
    RootsCapability,
    SamplingCapability,
    SamplingContextCapability,
    SamplingToolsCapability,
    UrlElicitationCapability,
)

_CLIENT_INFO = Implementation(name="t", version="0")
_MODERN = MODERN_PROTOCOL_VERSIONS[0]


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


# --- factories -----------------------------------------------------------------


def test_from_envelope_is_born_ready_with_no_back_channel():
    """SDK-defined: `from_envelope` populates `protocol_version`, sets `initialized`,
    and holds the no-channel sentinel so `has_standalone_channel` derives False."""
    conn = Connection.from_envelope(_MODERN, None, None)
    assert conn.protocol_version == _MODERN
    assert conn.initialized.is_set()
    assert conn.initialize_accepted is True
    assert conn.has_standalone_channel is False
    assert conn.client_params is None
    assert conn.session_id is None


def test_from_envelope_records_client_params_when_both_info_and_caps_supplied():
    """SDK-defined: when both client info and capabilities are supplied,
    `from_envelope` synthesizes `client_params` so capability checks can run."""
    caps = ClientCapabilities(sampling=SamplingCapability())
    conn = Connection.from_envelope(_MODERN, _CLIENT_INFO, caps)
    assert conn.client_params is not None
    assert conn.client_params.client_info.name == "t"
    assert conn.client_params.capabilities.sampling is not None
    assert conn.client_params.protocol_version == _MODERN


@pytest.mark.parametrize(
    ("info", "caps"),
    [(None, ClientCapabilities()), (_CLIENT_INFO, None)],
)
def test_from_envelope_leaves_client_params_none_when_either_is_missing(
    info: Implementation | None, caps: ClientCapabilities | None
):
    """SDK-defined: `client_params` is only synthesized when both info and
    caps are present; either missing leaves it `None`."""
    conn = Connection.from_envelope(_MODERN, info, caps)
    assert conn.client_params is None


def test_from_envelope_with_explicit_outbound_has_standalone_channel():
    """SDK-defined: duplex modern transports pass an outbound; `has_standalone_channel`
    derives True since the held outbound is not the no-channel sentinel."""
    out = StubOutbound()
    conn = Connection.from_envelope(_MODERN, None, None, outbound=out)
    assert conn.has_standalone_channel is True
    assert conn.outbound is out
    assert conn.initialized.is_set()


def test_for_loop_seeds_version_from_hint_or_latest_and_is_not_born_ready():
    """SDK-defined: `for_loop` seeds `protocol_version` from the hint when given,
    else `LATEST_PROTOCOL_VERSION`; the connection awaits the initialize handshake."""
    out = StubOutbound()
    conn = Connection.for_loop(out)
    assert conn.protocol_version == LATEST_PROTOCOL_VERSION
    assert conn.has_standalone_channel is True
    assert not conn.initialized.is_set()
    assert conn.initialize_accepted is False
    assert conn.client_params is None

    hinted = Connection.for_loop(out, protocol_version_hint=_MODERN)
    assert hinted.protocol_version == _MODERN


def test_for_loop_records_session_id_when_supplied():
    """SDK-defined: `for_loop` stores the `session_id` kwarg verbatim."""
    conn = Connection.for_loop(StubOutbound(), session_id="sess-1")
    assert conn.session_id == "sess-1"


# --- outbound channel ----------------------------------------------------------


@pytest.mark.anyio
async def test_connection_notify_forwards_to_outbound():
    out = StubOutbound()
    conn = Connection.for_loop(out)
    await conn.notify("notifications/message", {"level": "info", "data": "hi"})
    assert out.notifications == [("notifications/message", {"level": "info", "data": "hi"})]


@pytest.mark.anyio
async def test_connection_notify_swallows_broken_stream_and_debug_logs(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG, logger="mcp.server.connection")
    out = StubOutbound(raise_on_send=anyio.BrokenResourceError)
    conn = Connection.for_loop(out)
    await conn.notify("notifications/message", {"data": "x"})  # must not raise
    assert "stream closed" in caplog.text.lower()


@pytest.mark.anyio
async def test_connection_notify_drops_when_no_standalone_channel(caplog: pytest.LogCaptureFixture):
    """SDK-defined: the no-channel sentinel debug-logs and drops; `notify` never raises."""
    caplog.set_level(logging.DEBUG, logger="mcp.server.connection")
    conn = Connection.from_envelope(LATEST_PROTOCOL_VERSION, None, None)
    await conn.notify("notifications/message", {"data": "x"})  # must not raise
    assert "no standalone channel" in caplog.text.lower()


@pytest.mark.anyio
async def test_connection_send_raw_request_raises_nobackchannel_when_no_standalone_channel():
    """SDK-defined: the no-channel sentinel raises structurally; `Connection` does no pre-check."""
    conn = Connection.from_envelope(LATEST_PROTOCOL_VERSION, None, None)
    with pytest.raises(NoBackChannelError):
        await conn.send_raw_request("ping", None)


@pytest.mark.anyio
async def test_connection_send_raw_request_forwards_when_standalone_channel_present():
    out = StubOutbound()
    conn = Connection.for_loop(out)
    result = await conn.send_raw_request("ping", None)
    assert out.requests == [("ping", None)]
    assert result == {}


@pytest.mark.anyio
async def test_connection_send_request_with_spec_type_infers_result_type():
    out = StubOutbound(result={"roots": [{"uri": "file:///ws"}]})
    conn = Connection.for_loop(out)
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
    conn = Connection.for_loop(StubOutbound(result=snake))
    result = await conn.send_request(CreateMessageRequest(params=CreateMessageRequestParams(messages=[], max_tokens=1)))
    assert result.stop_reason is None


@pytest.mark.anyio
async def test_connection_send_request_with_result_type_kwarg_validates_custom_type():
    out = StubOutbound(result={})
    conn = Connection.for_loop(out)
    result = await conn.send_request(PingRequest(), result_type=EmptyResult)
    assert isinstance(result, EmptyResult)


@pytest.mark.anyio
async def test_connection_send_request_nonconforming_result_raises_validation_error():
    conn = Connection.for_loop(StubOutbound(result={"bogus": 1}))
    with pytest.raises(ValidationError):
        await conn.send_request(ListRootsRequest())


@pytest.mark.anyio
async def test_send_request_validates_the_client_result_against_the_surface_schema():
    """A spec-method result that fails the per-version surface schema raises
    `ValidationError` even when the caller's `result_type` would accept it."""
    conn = Connection.for_loop(StubOutbound(result={"roots": "nope"}))
    with pytest.raises(ValidationError):
        await conn.send_request(ListRootsRequest(), result_type=EmptyResult)


@pytest.mark.anyio
async def test_send_request_passes_a_spec_valid_client_result():
    """A spec-valid client result passes the surface gate and parses to the typed model."""
    conn = Connection.for_loop(StubOutbound(result={"roots": [{"uri": "file:///ws"}]}))
    assert conn.protocol_version == LATEST_PROTOCOL_VERSION
    result = await conn.send_request(ListRootsRequest())
    assert isinstance(result, ListRootsResult)
    assert str(result.roots[0].uri) == "file:///ws"


class _CustomRequest(Request[RequestParams | None, Literal["custom/echo"]]):
    method: Literal["custom/echo"] = "custom/echo"
    params: RequestParams | None = None


class _CustomResult(BaseModel):
    value: int


@pytest.mark.anyio
async def test_send_request_skips_the_surface_gate_when_method_absent_at_version():
    """Surface row absent for the negotiated version: gate is bypassed and only
    the inferred result type validates."""
    conn = Connection.for_loop(StubOutbound(result={}), protocol_version_hint=_MODERN)
    result = await conn.send_request(PingRequest())
    assert isinstance(result, EmptyResult)


@pytest.mark.anyio
async def test_send_request_with_a_custom_method_skips_the_surface_gate():
    """Non-spec methods are not blocked by the surface gate; `result_type` validates."""
    conn = Connection.for_loop(StubOutbound(result={"value": 7}))
    result = await conn.send_request(_CustomRequest(), result_type=_CustomResult)
    assert isinstance(result, _CustomResult)
    assert result.value == 7


@pytest.mark.anyio
async def test_connection_ping_sends_ping_on_standalone():
    out = StubOutbound()
    conn = Connection.for_loop(out)
    await conn.ping()
    assert out.requests == [("ping", None)]


@pytest.mark.anyio
async def test_connection_log_sends_logging_message_notification():
    out = StubOutbound()
    conn = Connection.for_loop(out)
    await conn.log("info", {"k": "v"}, logger="my.logger")  # pyright: ignore[reportDeprecated]
    method, params = out.notifications[0]
    assert method == "notifications/message"
    assert params is not None
    assert params["level"] == "info"
    assert params["data"] == {"k": "v"}
    assert params["logger"] == "my.logger"


@pytest.mark.anyio
async def test_connection_log_with_meta_includes_meta_in_params():
    out = StubOutbound()
    conn = Connection.for_loop(out)
    await conn.log("info", "x", meta={"traceId": "abc"})  # pyright: ignore[reportDeprecated]
    _, params = out.notifications[0]
    assert params is not None
    assert params["_meta"] == {"traceId": "abc"}


@pytest.mark.anyio
async def test_connection_list_changed_notifications_send_correct_methods():
    out = StubOutbound()
    conn = Connection.for_loop(out)
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
    conn = Connection.for_loop(out)
    await conn.send_tool_list_changed(meta={"k": 1})
    assert out.notifications == [("notifications/tools/list_changed", {"_meta": {"k": 1}})]


# --- check_capability ----------------------------------------------------------


def test_connection_check_capability_false_when_no_client_params_recorded():
    """SDK-defined: `check_capability` returns False when no `client_params`
    were recorded, regardless of which factory built the connection."""
    conn = Connection.for_loop(StubOutbound())
    assert conn.check_capability(ClientCapabilities(sampling=SamplingCapability())) is False
    # Same for a born-ready connection that supplied neither info nor caps.
    assert Connection.from_envelope(_MODERN, None, None).check_capability(ClientCapabilities()) is False


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
        (
            ClientCapabilities(sampling=SamplingCapability(context=SamplingContextCapability())),
            ClientCapabilities(sampling=SamplingCapability(context=SamplingContextCapability())),
            True,
        ),
        (ClientCapabilities(experimental=None), ClientCapabilities(experimental={"a": {}}), False),
        (ClientCapabilities(experimental={"a": {}}), ClientCapabilities(experimental={"b": {}}), False),
        (ClientCapabilities(experimental={"a": {"x": 1}}), ClientCapabilities(experimental={"a": {"x": 2}}), False),
        (ClientCapabilities(experimental={"a": {}}), ClientCapabilities(experimental={"a": {}}), True),
        # Elicitation sub-capability checks (form / url)
        (ClientCapabilities(elicitation=None), ClientCapabilities(elicitation=ElicitationCapability()), False),
        (
            ClientCapabilities(elicitation=ElicitationCapability(form=FormElicitationCapability())),
            ClientCapabilities(elicitation=ElicitationCapability(url=UrlElicitationCapability())),
            False,
        ),
        (
            ClientCapabilities(elicitation=ElicitationCapability(url=UrlElicitationCapability())),
            ClientCapabilities(elicitation=ElicitationCapability(form=FormElicitationCapability())),
            False,
        ),
        (
            ClientCapabilities(elicitation=ElicitationCapability(form=FormElicitationCapability(), url=UrlElicitationCapability())),
            ClientCapabilities(elicitation=ElicitationCapability(form=FormElicitationCapability())),
            True,
        ),
        (
            ClientCapabilities(elicitation=ElicitationCapability(form=FormElicitationCapability())),
            ClientCapabilities(elicitation=ElicitationCapability(form=FormElicitationCapability())),
            True,
        ),
    ],
)
def test_check_capability_per_field_branches(have: ClientCapabilities, want: ClientCapabilities, expected: bool):
    conn = Connection.from_envelope(LATEST_PROTOCOL_VERSION, _CLIENT_INFO, have)
    assert conn.check_capability(want) is expected


def test_connection_check_capability_true_when_client_declares_it():
    conn = Connection.from_envelope(
        LATEST_PROTOCOL_VERSION,
        _CLIENT_INFO,
        ClientCapabilities(sampling=SamplingCapability(), roots=RootsCapability(list_changed=True)),
    )
    assert conn.check_capability(ClientCapabilities(sampling=SamplingCapability())) is True
    assert conn.check_capability(ClientCapabilities(roots=RootsCapability(list_changed=True))) is True
    assert conn.check_capability(ClientCapabilities(elicitation=ElicitationCapability())) is False
