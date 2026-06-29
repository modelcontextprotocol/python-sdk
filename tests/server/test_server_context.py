"""Tests for the server-side `Context`, exercised end-to-end over `DirectDispatcher`."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import anyio
import pytest

from mcp.server.connection import Connection
from mcp.server.context import Context
from mcp.shared.dispatcher import DispatchContext
from mcp.shared.transport_context import TransportContext

from ..shared.conftest import direct_pair
from ..shared.test_dispatcher import Recorder, echo_handlers, running_pair

DCtx = DispatchContext[TransportContext]


@dataclass
class _Lifespan:
    name: str


@pytest.mark.anyio
async def test_context_exposes_lifespan_and_connection_and_forwards_base_context():
    captured: list[Context[_Lifespan]] = []
    conn_holder: list[Connection] = []

    async def server_on_request(dctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        ctx: Context[_Lifespan] = Context(dctx, lifespan=_Lifespan("app"), connection=conn_holder[0])
        captured.append(ctx)
        return {}

    async with running_pair(direct_pair, server_on_request=server_on_request) as (client, server, *_):
        conn_holder.append(Connection.for_loop(server, session_id="sess-1"))
        with anyio.fail_after(5):
            await client.send_raw_request("t", None)
        ctx = captured[0]
        assert ctx.lifespan.name == "app"
        assert ctx.connection is conn_holder[0]
        assert ctx.transport.kind == "direct"
        assert ctx.can_send_request is True
        assert ctx.session_id == "sess-1"
        assert ctx.headers is None


@pytest.mark.anyio
async def test_context_log_sends_request_scoped_message_notification():
    crec = Recorder()
    _, c_notify = echo_handlers(crec)

    async def server_on_request(dctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        ctx: Context[_Lifespan] = Context(dctx, lifespan=_Lifespan("app"), connection=Connection.for_loop(dctx))
        await ctx.log("debug", "hello")  # pyright: ignore[reportDeprecated]
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
        ctx: Context[_Lifespan] = Context(dctx, lifespan=_Lifespan("app"), connection=Connection.for_loop(dctx))
        await ctx.log("info", "x", logger="my.log", meta={"traceId": "t"})  # pyright: ignore[reportDeprecated]
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
