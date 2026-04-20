"""Tests for `PeerMixin` and `Peer`.

Each PeerMixin method is tested by wrapping a `DirectDispatcher` in `Peer`,
calling the typed method, and asserting (a) the right method+params went out
and (b) the return value is the typed result model.
"""

from collections.abc import Mapping
from typing import Any

import anyio
import pytest

from mcp.shared.dispatcher import DispatchContext
from mcp.shared.peer import Peer, dump_params
from mcp.shared.transport_context import TransportContext
from mcp.types import (
    CreateMessageResult,
    CreateMessageResultWithTools,
    ElicitResult,
    ListRootsResult,
    SamplingMessage,
    TextContent,
    Tool,
)

from .conftest import direct_pair
from .test_dispatcher import running_pair

DCtx = DispatchContext[TransportContext]


class _Recorder:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.seen: list[tuple[str, Mapping[str, Any] | None]] = []

    async def on_request(self, ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        self.seen.append((method, params))
        return self.result


@pytest.mark.anyio
async def test_peer_sample_sends_create_message_and_returns_typed_result():
    rec = _Recorder({"role": "assistant", "content": {"type": "text", "text": "hi"}, "model": "m"})
    async with running_pair(direct_pair, server_on_request=rec.on_request) as (client, *_):
        peer = Peer(client)
        with anyio.fail_after(5):
            result = await peer.sample(
                [SamplingMessage(role="user", content=TextContent(type="text", text="hello"))],
                max_tokens=10,
            )
        method, params = rec.seen[0]
        assert method == "sampling/createMessage"
        assert params is not None and params["maxTokens"] == 10
        assert isinstance(result, CreateMessageResult)
        assert result.model == "m"


@pytest.mark.anyio
async def test_peer_sample_with_tools_returns_with_tools_result():
    rec = _Recorder({"role": "assistant", "content": [{"type": "text", "text": "x"}], "model": "m"})
    async with running_pair(direct_pair, server_on_request=rec.on_request) as (client, *_):
        peer = Peer(client)
        with anyio.fail_after(5):
            result = await peer.sample(
                [SamplingMessage(role="user", content=TextContent(type="text", text="q"))],
                max_tokens=5,
                tools=[Tool(name="t", input_schema={"type": "object"})],
            )
        method, params = rec.seen[0]
        assert method == "sampling/createMessage"
        assert params is not None and params["tools"][0]["name"] == "t"
        assert isinstance(result, CreateMessageResultWithTools)


@pytest.mark.anyio
async def test_peer_elicit_form_sends_elicitation_create_with_form_params():
    rec = _Recorder({"action": "accept", "content": {"name": "Max"}})
    async with running_pair(direct_pair, server_on_request=rec.on_request) as (client, *_):
        peer = Peer(client)
        with anyio.fail_after(5):
            result = await peer.elicit_form("Your name?", requested_schema={"type": "object", "properties": {}})
        method, params = rec.seen[0]
        assert method == "elicitation/create"
        assert params is not None and params["mode"] == "form"
        assert params["message"] == "Your name?"
        assert isinstance(result, ElicitResult)


@pytest.mark.anyio
async def test_peer_elicit_url_sends_elicitation_create_with_url_params():
    rec = _Recorder({"action": "accept"})
    async with running_pair(direct_pair, server_on_request=rec.on_request) as (client, *_):
        peer = Peer(client)
        with anyio.fail_after(5):
            result = await peer.elicit_url("Auth needed", url="https://example.com/auth", elicitation_id="e1")
        method, params = rec.seen[0]
        assert method == "elicitation/create"
        assert params is not None and params["mode"] == "url"
        assert params["url"] == "https://example.com/auth"
        assert isinstance(result, ElicitResult)


@pytest.mark.anyio
async def test_peer_list_roots_sends_roots_list_and_returns_typed_result():
    rec = _Recorder({"roots": [{"uri": "file:///workspace"}]})
    async with running_pair(direct_pair, server_on_request=rec.on_request) as (client, *_):
        peer = Peer(client)
        with anyio.fail_after(5):
            result = await peer.list_roots()
        method, _ = rec.seen[0]
        assert method == "roots/list"
        assert isinstance(result, ListRootsResult)
        assert len(result.roots) == 1
        assert str(result.roots[0].uri) == "file:///workspace"


@pytest.mark.anyio
async def test_peer_list_roots_with_meta_sends_meta_in_params():
    rec = _Recorder({"roots": []})
    async with running_pair(direct_pair, server_on_request=rec.on_request) as (client, *_):
        peer = Peer(client)
        with anyio.fail_after(5):
            await peer.list_roots(meta={"traceId": "t1"})
        method, params = rec.seen[0]
        assert method == "roots/list"
        assert params == {"_meta": {"traceId": "t1"}}


def test_dump_params_merges_meta_over_model_meta():
    out = dump_params(None, None)
    assert out is None
    out = dump_params(None, {"k": 1})
    assert out == {"_meta": {"k": 1}}


@pytest.mark.anyio
async def test_peer_notify_forwards_to_wrapped_outbound():
    sent: list[tuple[str, Mapping[str, Any] | None]] = []

    class _Out:
        async def send_raw_request(
            self, method: str, params: Mapping[str, Any] | None, opts: Any = None
        ) -> dict[str, Any]:
            raise NotImplementedError

        async def notify(self, method: str, params: Mapping[str, Any] | None) -> None:
            sent.append((method, params))

    await Peer(_Out()).notify("n", {"x": 1})
    assert sent == [("n", {"x": 1})]


@pytest.mark.anyio
async def test_peer_ping_sends_ping_and_returns_none():
    rec = _Recorder({})
    async with running_pair(direct_pair, server_on_request=rec.on_request) as (client, *_):
        peer = Peer(client)
        with anyio.fail_after(5):
            result = await peer.ping()
        method, _ = rec.seen[0]
        assert method == "ping"
        assert result is None
