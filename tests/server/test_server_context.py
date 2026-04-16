"""Tests for the server-side `Context`.

`Context` composes `BaseContext` (forwarding to a `DispatchContext`) with
`PeerMixin` (typed sample/elicit/roots/ping) plus `lifespan` and `connection`.
End-to-end tested over `DirectDispatcher`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import anyio
import pytest

from mcp.server.connection import Connection
from mcp.server.context import Context
from mcp.shared.dispatcher import DispatchContext
from mcp.shared.transport_context import TransportContext
from mcp.types import CreateMessageResult, ListRootsRequest, ListRootsResult, SamplingMessage, TextContent

from ..shared.conftest import direct_pair
from ..shared.test_dispatcher import Recorder, echo_handlers, running_pair

DCtx = DispatchContext[TransportContext]


@dataclass
class _Lifespan:
    name: str


@pytest.mark.anyio
async def test_context_exposes_lifespan_and_connection_and_forwards_base_context():
    captured: list[Context[_Lifespan, TransportContext]] = []
    conn = Connection.__new__(Connection)  # placeholder until running_pair gives us the dispatcher

    async def server_on_request(dctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        ctx: Context[_Lifespan, TransportContext] = Context(dctx, lifespan=_Lifespan("app"), connection=conn)
        captured.append(ctx)
        return {}

    async with running_pair(direct_pair, server_on_request=server_on_request) as (client, server, *_):
        # Now we have the server dispatcher; build the real Connection bound to it.
        conn.__init__(server, has_standalone_channel=True)
        with anyio.fail_after(5):
            await client.send_raw_request("t", None)
    ctx = captured[0]
    assert ctx.lifespan.name == "app"
    assert ctx.connection is conn
    assert ctx.transport.kind == "direct"
    assert ctx.can_send_request is True


@pytest.mark.anyio
async def test_context_sample_round_trips_via_peer_mixin_on_base_context_outbound():
    crec = Recorder()

    async def client_on_request(dctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        crec.requests.append((method, params))
        return {"role": "assistant", "content": {"type": "text", "text": "ok"}, "model": "m"}

    results: list[CreateMessageResult] = []

    async def server_on_request(dctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        ctx: Context[_Lifespan, TransportContext] = Context(
            dctx, lifespan=_Lifespan("app"), connection=Connection(dctx, has_standalone_channel=True)
        )
        results.append(
            await ctx.sample(
                [SamplingMessage(role="user", content=TextContent(type="text", text="hi"))],
                max_tokens=5,
            )
        )
        return {}

    async with running_pair(
        direct_pair,
        server_on_request=server_on_request,
        client_on_request=client_on_request,
    ) as (client, *_):
        with anyio.fail_after(5):
            await client.send_raw_request("tools/call", None)
    assert crec.requests[0][0] == "sampling/createMessage"
    assert isinstance(results[0], CreateMessageResult)


@pytest.mark.anyio
async def test_context_send_request_with_spec_type_infers_result_via_typed_mixin():
    async def client_on_request(dctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        return {"roots": []}

    results: list[ListRootsResult] = []

    async def server_on_request(dctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        ctx: Context[_Lifespan, TransportContext] = Context(
            dctx, lifespan=_Lifespan("app"), connection=Connection(dctx, has_standalone_channel=True)
        )
        results.append(await ctx.send_request(ListRootsRequest()))
        return {}

    async with running_pair(direct_pair, server_on_request=server_on_request, client_on_request=client_on_request) as (
        client,
        *_,
    ):
        with anyio.fail_after(5):
            await client.send_raw_request("t", None)
    assert isinstance(results[0], ListRootsResult)


@pytest.mark.anyio
async def test_context_log_sends_request_scoped_message_notification():
    crec = Recorder()
    _, c_notify = echo_handlers(crec)

    async def server_on_request(dctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        ctx: Context[_Lifespan, TransportContext] = Context(
            dctx, lifespan=_Lifespan("app"), connection=Connection(dctx, has_standalone_channel=True)
        )
        await ctx.log("debug", "hello")
        return {}

    async with running_pair(direct_pair, server_on_request=server_on_request, client_on_notify=c_notify) as (
        client,
        *_,
    ):
        with anyio.fail_after(5):
            await client.send_raw_request("t", None)
            await crec.notified.wait()
    method, params = crec.notifications[0]
    assert method == "notifications/message"
    assert params is not None and params["level"] == "debug" and params["data"] == "hello"


@pytest.mark.anyio
async def test_context_log_includes_logger_and_meta_when_supplied():
    crec = Recorder()
    _, c_notify = echo_handlers(crec)

    async def server_on_request(dctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        ctx: Context[_Lifespan, TransportContext] = Context(
            dctx, lifespan=_Lifespan("app"), connection=Connection(dctx, has_standalone_channel=True)
        )
        await ctx.log("info", "x", logger="my.log", meta={"traceId": "t"})
        return {}

    async with running_pair(direct_pair, server_on_request=server_on_request, client_on_notify=c_notify) as (
        client,
        *_,
    ):
        with anyio.fail_after(5):
            await client.send_raw_request("t", None)
            await crec.notified.wait()
    _, params = crec.notifications[0]
    assert params is not None
    assert params["logger"] == "my.log"
    assert params["_meta"] == {"traceId": "t"}
