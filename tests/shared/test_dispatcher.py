"""Behavioral tests for the Dispatcher Protocol via DirectDispatcher.

These exercise the `Dispatcher` / `DispatchContext` contract end-to-end using
the in-memory `DirectDispatcher`. JSON-RPC framing is covered separately in
``test_jsonrpc_dispatcher.py``.
"""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import anyio
import pytest

from mcp.shared.direct_dispatcher import DirectDispatcher, create_direct_dispatcher_pair
from mcp.shared.dispatcher import DispatchContext, Dispatcher, OnNotify, OnRequest, Outbound
from mcp.shared.exceptions import MCPError, NoBackChannelError
from mcp.shared.transport_context import TransportContext
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS, INVALID_REQUEST, REQUEST_TIMEOUT


class Recorder:
    def __init__(self) -> None:
        self.requests: list[tuple[str, Mapping[str, Any] | None]] = []
        self.notifications: list[tuple[str, Mapping[str, Any] | None]] = []
        self.contexts: list[DispatchContext[TransportContext]] = []
        self.notified = anyio.Event()


def echo_handlers(recorder: Recorder) -> tuple[OnRequest, OnNotify]:
    async def on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        recorder.requests.append((method, params))
        recorder.contexts.append(ctx)
        return {"echoed": method, "params": dict(params or {})}

    async def on_notify(ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None) -> None:
        recorder.notifications.append((method, params))
        recorder.notified.set()

    return on_request, on_notify


@asynccontextmanager
async def running_pair(
    *,
    server_on_request: OnRequest | None = None,
    server_on_notify: OnNotify | None = None,
    client_on_request: OnRequest | None = None,
    client_on_notify: OnNotify | None = None,
    can_send_request: bool = True,
) -> AsyncIterator[tuple[DirectDispatcher, DirectDispatcher, Recorder, Recorder]]:
    """Yield ``(client, server, client_recorder, server_recorder)`` with both ``run()`` loops live."""
    client, server = create_direct_dispatcher_pair(can_send_request=can_send_request)
    client_rec, server_rec = Recorder(), Recorder()
    c_req, c_notify = echo_handlers(client_rec)
    s_req, s_notify = echo_handlers(server_rec)
    async with anyio.create_task_group() as tg:
        tg.start_soon(client.run, client_on_request or c_req, client_on_notify or c_notify)
        tg.start_soon(server.run, server_on_request or s_req, server_on_notify or s_notify)
        try:
            yield client, server, client_rec, server_rec
        finally:
            client.close()
            server.close()


@pytest.mark.anyio
async def test_send_request_returns_result_from_peer_on_request():
    async with running_pair() as (client, _server, _crec, srec):
        with anyio.fail_after(5):
            result = await client.send_request("tools/list", {"cursor": "abc"})
    assert result == {"echoed": "tools/list", "params": {"cursor": "abc"}}
    assert srec.requests == [("tools/list", {"cursor": "abc"})]


@pytest.mark.anyio
async def test_send_request_reraises_mcperror_from_handler_unchanged():
    async def on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        raise MCPError(code=INVALID_PARAMS, message="bad cursor")

    async with running_pair(server_on_request=on_request) as (client, *_):
        with anyio.fail_after(5), pytest.raises(MCPError) as exc:
            await client.send_request("tools/list", {})
    assert exc.value.error.code == INVALID_PARAMS
    assert exc.value.error.message == "bad cursor"


@pytest.mark.anyio
async def test_send_request_wraps_non_mcperror_exception_as_internal_error():
    async def on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        raise ValueError("oops")

    async with running_pair(server_on_request=on_request) as (client, *_):
        with anyio.fail_after(5), pytest.raises(MCPError) as exc:
            await client.send_request("tools/list", {})
    assert exc.value.error.code == INTERNAL_ERROR
    assert isinstance(exc.value.__cause__, ValueError)


@pytest.mark.anyio
async def test_send_request_with_timeout_raises_mcperror_request_timeout():
    async def on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        await anyio.sleep_forever()
        raise NotImplementedError

    async with running_pair(server_on_request=on_request) as (client, *_):
        with anyio.fail_after(5), pytest.raises(MCPError) as exc:
            await client.send_request("slow", None, {"timeout": 0})
    assert exc.value.error.code == REQUEST_TIMEOUT


@pytest.mark.anyio
async def test_notify_invokes_peer_on_notify():
    async with running_pair() as (client, _server, _crec, srec):
        with anyio.fail_after(5):
            await client.notify("notifications/initialized", {"v": 1})
            await srec.notified.wait()
    assert srec.notifications == [("notifications/initialized", {"v": 1})]


@pytest.mark.anyio
async def test_ctx_send_request_round_trips_to_calling_side():
    """A handler's ctx.send_request reaches the side that made the inbound request."""

    async def server_on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        sample = await ctx.send_request("sampling/createMessage", {"prompt": "hi"})
        return {"sampled": sample}

    async with running_pair(server_on_request=server_on_request) as (client, _server, crec, _srec):
        with anyio.fail_after(5):
            result = await client.send_request("tools/call", None)
    assert crec.requests == [("sampling/createMessage", {"prompt": "hi"})]
    assert result == {"sampled": {"echoed": "sampling/createMessage", "params": {"prompt": "hi"}}}


@pytest.mark.anyio
async def test_ctx_send_request_raises_nobackchannelerror_when_transport_disallows():
    async def server_on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        return await ctx.send_request("sampling/createMessage", None)

    async with running_pair(server_on_request=server_on_request, can_send_request=False) as (client, *_):
        with anyio.fail_after(5), pytest.raises(NoBackChannelError) as exc:
            await client.send_request("tools/call", None)
    assert exc.value.method == "sampling/createMessage"
    assert exc.value.error.code == INVALID_REQUEST


@pytest.mark.anyio
async def test_ctx_notify_invokes_calling_side_on_notify():
    async def server_on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        await ctx.notify("notifications/message", {"level": "info"})
        return {}

    async with running_pair(server_on_request=server_on_request) as (client, _server, crec, _srec):
        with anyio.fail_after(5):
            await client.send_request("tools/call", None)
            await crec.notified.wait()
    assert crec.notifications == [("notifications/message", {"level": "info"})]


@pytest.mark.anyio
async def test_ctx_progress_invokes_caller_on_progress_callback():
    async def server_on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        await ctx.progress(0.5, total=1.0, message="halfway")
        return {}

    received: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        received.append((progress, total, message))

    async with running_pair(server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5):
            await client.send_request("tools/call", None, {"on_progress": on_progress})
    assert received == [(0.5, 1.0, "halfway")]


@pytest.mark.anyio
async def test_send_request_issued_before_peer_run_blocks_until_peer_ready():
    client, server = create_direct_dispatcher_pair()
    s_req, s_notify = echo_handlers(Recorder())
    c_req, c_notify = echo_handlers(Recorder())

    async def late_start():
        await anyio.sleep(0)
        await server.run(s_req, s_notify)

    async with anyio.create_task_group() as tg:
        tg.start_soon(client.run, c_req, c_notify)
        tg.start_soon(late_start)
        with anyio.fail_after(5):
            result = await client.send_request("ping", None)
        assert result == {"echoed": "ping", "params": {}}
        client.close()
        server.close()


@pytest.mark.anyio
async def test_ctx_progress_is_noop_when_caller_supplied_no_callback():
    async def server_on_request(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        await ctx.progress(0.5)
        return {"ok": True}

    async with running_pair(server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5):
            result = await client.send_request("tools/call", None)
    assert result == {"ok": True}


@pytest.mark.anyio
async def test_send_request_and_notify_raise_runtimeerror_when_no_peer_connected():
    d = DirectDispatcher(TransportContext(kind="direct", can_send_request=True))
    with pytest.raises(RuntimeError, match="no peer"):
        await d.send_request("ping", None)
    with pytest.raises(RuntimeError, match="no peer"):
        await d.notify("ping", None)


@pytest.mark.anyio
async def test_close_makes_run_return():
    client, server = create_direct_dispatcher_pair()
    on_request, on_notify = echo_handlers(Recorder())
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(server.run, on_request, on_notify)
            tg.start_soon(client.run, on_request, on_notify)
            client.close()
            server.close()


if TYPE_CHECKING:
    _d: Dispatcher[TransportContext] = DirectDispatcher(TransportContext(kind="direct", can_send_request=True))
    _o: Outbound = _d
