"""Tests for `ServerSession`.

`ServerSession` is a thin proxy over a dispatcher and a `Connection`. Tested
with a stub dispatcher so we can assert what reaches the wire (method, params,
`CallOptions`, related-request-id) without standing up a full transport.
"""

from collections.abc import Mapping
from typing import Any, cast

import pytest

from mcp import types
from mcp.server.connection import Connection
from mcp.server.session import ServerSession
from mcp.shared.dispatcher import CallOptions
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


def _make_session(dispatcher: StubDispatcher, *, capabilities: ClientCapabilities | None = None) -> ServerSession:
    conn = Connection(dispatcher, has_standalone_channel=True)
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
        types.ListRootsRequest(),
        types.ListRootsResult,
        request_read_timeout_seconds=2.5,
        metadata=ServerMessageMetadata(related_request_id=7),
        progress_callback=on_progress,
    )
    assert isinstance(result, types.ListRootsResult)
    method, _params, opts, related = dispatcher.requests[0]
    assert method == "roots/list"
    assert opts == {"timeout": 2.5, "on_progress": on_progress}
    assert related == 7


@pytest.mark.anyio
async def test_send_request_omits_call_options_when_none_given():
    dispatcher = StubDispatcher(result={"roots": []})
    session = _make_session(dispatcher)
    await session.send_request(types.ListRootsRequest(), types.ListRootsResult)
    _method, _params, opts, related = dispatcher.requests[0]
    assert opts is None
    assert related is None


@pytest.mark.anyio
async def test_send_request_validates_result_alias_only():
    """Peer results validate alias-only; a snake_case key from the wire is
    ignored as extra, not populated by Python field name."""
    snake = {"role": "assistant", "content": {"type": "text", "text": "x"}, "model": "m", "stop_reason": "endTurn"}
    session = _make_session(StubDispatcher(result=snake))
    request = types.CreateMessageRequest(params=types.CreateMessageRequestParams(messages=[], max_tokens=1))
    result = await session.send_request(request, types.CreateMessageResult)
    assert result.stop_reason is None


@pytest.mark.anyio
async def test_create_message_with_tools_returns_with_tools_result():
    dispatcher = StubDispatcher(result={"role": "assistant", "content": [{"type": "text", "text": "ok"}], "model": "m"})
    session = _make_session(
        dispatcher, capabilities=ClientCapabilities(sampling=SamplingCapability(tools=SamplingToolsCapability()))
    )
    result = await session.create_message(
        messages=[types.SamplingMessage(role="user", content=types.TextContent(type="text", text="hi"))],
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
