"""Tests for `ServerSession`.

`ServerSession` is a thin proxy over a dispatcher and a `Connection`. Tested
with a stub dispatcher so we can assert what reaches the wire (method, params,
`CallOptions`, related-request-id) without standing up a full transport.
"""

from collections.abc import Mapping
from typing import Any, cast

import pytest
from pydantic import ValidationError

from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.server.connection import Connection
from mcp.server.session import ServerSession
from mcp.shared.dispatcher import CallOptions
from mcp.shared.exceptions import NoBackChannelError
from mcp.shared.jsonrpc_dispatcher import JSONRPCDispatcher
from mcp.shared.message import ServerMessageMetadata
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    ClientCapabilities,
    Implementation,
    InitializeRequestParams,
    SamplingCapability,
    SamplingToolsCapability,
)

from .test_runner import connected_runner


class StubDispatcher:
    """Records `send_raw_request` / `notify` calls and returns a canned result."""

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.requests: list[tuple[str, Mapping[str, Any] | None, CallOptions | None, Any]] = []
        self.result = result if result is not None else {}

    async def send_raw_request(
        self,
        method: str,
        params: Mapping[str, Any] | None,
        opts: CallOptions | None = None,
        *,
        _related_request_id: Any = None,
    ) -> dict[str, Any]:
        self.requests.append((method, params, opts, _related_request_id))
        return self.result

    async def notify(self, method: str, params: Mapping[str, Any] | None) -> None:
        raise NotImplementedError


def _make_session(
    dispatcher: StubDispatcher,
    *,
    capabilities: ClientCapabilities | None = None,
    has_standalone_channel: bool = True,
    protocol_version: str | None = None,
) -> ServerSession:
    conn = Connection(dispatcher, has_standalone_channel=has_standalone_channel)
    conn.protocol_version = protocol_version
    if capabilities is not None:
        conn.client_params = InitializeRequestParams(
            protocol_version=LATEST_PROTOCOL_VERSION,
            capabilities=capabilities,
            client_info=Implementation(name="c", version="0"),
        )
    # cast: `ServerSession` is typed to take `JSONRPCDispatcher` but only ever
    # calls `send_raw_request` / `notify`, so the stub is structurally sufficient.
    return ServerSession(cast("JSONRPCDispatcher[Any]", dispatcher), conn)


@pytest.mark.anyio
async def test_send_request_forwards_timeout_and_progress_callback_as_call_options():
    dispatcher = StubDispatcher(result={"roots": []})
    session = _make_session(dispatcher)

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        raise NotImplementedError

    result = await session.send_request(
        types.ListRootsRequest(),  # pyright: ignore[reportDeprecated]
        types.ListRootsResult,  # pyright: ignore[reportDeprecated]
        request_read_timeout_seconds=2.5,
        metadata=ServerMessageMetadata(related_request_id=7),
        progress_callback=on_progress,
    )
    assert isinstance(result, types.ListRootsResult)  # pyright: ignore[reportDeprecated]
    method, _params, opts, related = dispatcher.requests[0]
    assert method == "roots/list"
    assert opts == {"timeout": 2.5, "on_progress": on_progress}
    assert related == 7


@pytest.mark.anyio
async def test_send_request_omits_call_options_when_none_given():
    dispatcher = StubDispatcher(result={"roots": []})
    session = _make_session(dispatcher)
    await session.send_request(types.ListRootsRequest(), types.ListRootsResult)  # pyright: ignore[reportDeprecated]
    _method, _params, opts, related = dispatcher.requests[0]
    assert opts is None
    assert related is None


@pytest.mark.anyio
async def test_send_request_timeout_zero_is_forwarded():
    """0 is a real timeout (fail at the first checkpoint, `anyio.fail_after(0)`
    semantics) and must reach the dispatcher; only `None` means "no timeout"."""
    dispatcher = StubDispatcher(result={})
    session = _make_session(dispatcher)
    await session.send_request(types.PingRequest(), types.EmptyResult, request_read_timeout_seconds=0.0)
    assert dispatcher.requests[0][2] == {"timeout": 0.0}


@pytest.mark.anyio
async def test_send_request_without_back_channel_or_related_id_fails_fast():
    """No standalone channel and no related request to ride on: raise instead
    of parking forever on a response that cannot arrive."""
    dispatcher = StubDispatcher(result={})
    session = _make_session(dispatcher, has_standalone_channel=False)
    with pytest.raises(NoBackChannelError):
        await session.send_request(types.PingRequest(), types.EmptyResult)
    assert dispatcher.requests == []
    # With a related request id the message rides that request's stream.
    await session.send_request(
        types.PingRequest(), types.EmptyResult, metadata=ServerMessageMetadata(related_request_id=3)
    )
    assert dispatcher.requests[0][3] == 3


@pytest.mark.anyio
async def test_send_request_validates_the_client_result_against_the_surface_schema():
    """A spec-method result that fails the per-version surface schema raises
    `ValidationError` even when the caller's `result_type` would accept it."""
    session = _make_session(StubDispatcher(result={"roots": "nope"}))
    with pytest.raises(ValidationError):
        await session.send_request(types.ListRootsRequest(), types.EmptyResult)  # pyright: ignore[reportDeprecated]


@pytest.mark.anyio
async def test_send_request_passes_a_spec_valid_client_result():
    """A spec-valid client result passes the surface gate and parses to the typed model."""
    session = _make_session(StubDispatcher(result={"roots": [{"uri": "file:///ws"}]}))
    result = await session.send_request(types.ListRootsRequest(), types.ListRootsResult)  # pyright: ignore[reportDeprecated]
    assert isinstance(result, types.ListRootsResult)  # pyright: ignore[reportDeprecated]
    assert str(result.roots[0].uri) == "file:///ws"


@pytest.mark.anyio
async def test_send_request_skips_the_surface_gate_when_method_absent_at_version():
    """Surface row absent for the negotiated version: gate is bypassed and only
    `result_type` validates."""
    session = _make_session(StubDispatcher(result={}), protocol_version="2026-07-28")
    result = await session.send_request(types.PingRequest(), types.EmptyResult)
    assert isinstance(result, types.EmptyResult)


@pytest.mark.anyio
async def test_send_request_validates_result_alias_only():
    """Peer results validate alias-only; a snake_case key from the wire is
    ignored as extra, not populated by Python field name."""
    snake = {"role": "assistant", "content": {"type": "text", "text": "x"}, "model": "m", "stop_reason": "endTurn"}
    session = _make_session(StubDispatcher(result=snake))
    request = types.CreateMessageRequest(params=types.CreateMessageRequestParams(messages=[], max_tokens=1))  # pyright: ignore[reportDeprecated]
    result = await session.send_request(request, types.CreateMessageResult)  # pyright: ignore[reportDeprecated]
    assert result.stop_reason is None


@pytest.mark.anyio
async def test_create_message_with_tools_returns_with_tools_result():
    dispatcher = StubDispatcher(result={"role": "assistant", "content": [{"type": "text", "text": "ok"}], "model": "m"})
    session = _make_session(
        dispatcher, capabilities=ClientCapabilities(sampling=SamplingCapability(tools=SamplingToolsCapability()))
    )
    result = await session.create_message(
        messages=[types.SamplingMessage(role="user", content=types.TextContent(type="text", text="hi"))],  # pyright: ignore[reportDeprecated]
        max_tokens=10,
        tools=[types.Tool(name="t", input_schema={"type": "object"})],
    )
    assert isinstance(result, types.CreateMessageResultWithTools)
    method, params, _opts, _related = dispatcher.requests[0]
    assert method == "sampling/createMessage"
    assert params is not None and params["tools"][0]["name"] == "t"


def test_check_client_capability_delegates_to_connection():
    dispatcher = StubDispatcher()
    session = _make_session(dispatcher, capabilities=ClientCapabilities(sampling=SamplingCapability()))
    assert session.check_client_capability(ClientCapabilities(sampling=SamplingCapability())) is True
    assert session.check_client_capability(ClientCapabilities(experimental={"x": {}})) is False


def _runner_server(seen_versions: list[str | None]) -> Server[dict[str, Any]]:
    """A lowlevel Server whose tools/list handler records `ctx.session.protocol_version`."""

    async def list_tools(
        ctx: ServerRequestContext[dict[str, Any], Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        seen_versions.append(ctx.session.protocol_version)
        return types.ListToolsResult(tools=[])

    return Server(name="test-server", version="0.0.1", on_list_tools=list_tools)


def _init_params(protocol_version: str) -> dict[str, Any]:
    return InitializeRequestParams(
        protocol_version=protocol_version,
        capabilities=ClientCapabilities(),
        client_info=Implementation(name="test-client", version="1.0"),
    ).model_dump(by_alias=True, exclude_none=True)


@pytest.mark.anyio
async def test_protocol_version_is_none_before_initialize():
    """No negotiated version is readable before the initialize handshake."""
    async with connected_runner(_runner_server([]), initialized=False) as (_client, runner):
        assert runner.session.protocol_version is None


@pytest.mark.anyio
async def test_protocol_version_is_negotiated_version_after_initialize():
    """A supported requested version is echoed back and readable on the session,
    both directly and from inside a handler via `ctx.session`."""
    seen: list[str | None] = []
    async with connected_runner(_runner_server(seen), initialized=False) as (client, runner):
        result = await client.send_raw_request("initialize", _init_params("2025-03-26"))
        assert result["protocolVersion"] == "2025-03-26"
        assert runner.session.protocol_version == "2025-03-26"
        await client.send_raw_request("tools/list", None)
        assert seen == ["2025-03-26"]


@pytest.mark.anyio
async def test_protocol_version_reads_latest_when_requested_version_unsupported():
    """An unsupported requested version negotiates down to LATEST_PROTOCOL_VERSION."""
    async with connected_runner(_runner_server([]), initialized=False) as (client, runner):
        result = await client.send_raw_request("initialize", _init_params("1999-01-01"))
        assert result["protocolVersion"] == LATEST_PROTOCOL_VERSION
        assert runner.session.protocol_version == LATEST_PROTOCOL_VERSION


@pytest.mark.anyio
async def test_protocol_version_is_none_on_stateless_connection():
    """Stateless connections never see a handshake: requests flow, but the
    negotiated version legitimately stays None."""
    seen: list[str | None] = []
    async with connected_runner(_runner_server(seen), initialized=False, stateless=True) as (client, runner):
        result = await client.send_raw_request("tools/list", None)
        assert result == {"tools": []}
        assert seen == [None]
        assert runner.session.protocol_version is None
