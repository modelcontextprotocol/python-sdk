"""Tests for `BaseContext`.

`BaseContext` is composition over a `DispatchContext` — it forwards
``transport``/``cancel_requested``/``send_raw_request``/``notify``/``progress``
and adds ``meta``. It must satisfy `Outbound` so `PeerMixin` works on it.
"""

from collections.abc import Mapping
from typing import Any

import anyio
import pytest

from mcp.shared.context import BaseContext
from mcp.shared.dispatcher import DispatchContext
from mcp.shared.peer import Peer
from mcp.shared.transport_context import TransportContext

from .conftest import direct_pair
from .test_dispatcher import Recorder, echo_handlers, running_pair

DCtx = DispatchContext[TransportContext]


@pytest.mark.anyio
async def test_base_context_forwards_transport_and_cancel_requested():
    captured: list[BaseContext[TransportContext]] = []

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        bctx = BaseContext(ctx)
        captured.append(bctx)
        return {}

    async with running_pair(direct_pair, server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5):
            await client.send_raw_request("t", None)
        bctx = captured[0]
        assert bctx.transport.kind == "direct"
        assert isinstance(bctx.cancel_requested, anyio.Event)
        assert bctx.can_send_request is True
        assert bctx.meta is None


@pytest.mark.anyio
async def test_base_context_send_raw_request_and_notify_forward_to_dispatch_context():
    crec = Recorder()
    c_req, c_notify = echo_handlers(crec)

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        bctx = BaseContext(ctx)
        sample = await bctx.send_raw_request("sampling/createMessage", {"x": 1})
        await bctx.notify("notifications/message", {"level": "info"})
        return {"sample": sample}

    async with running_pair(
        direct_pair,
        server_on_request=server_on_request,
        client_on_request=c_req,
        client_on_notify=c_notify,
    ) as (client, *_):
        with anyio.fail_after(5):
            result = await client.send_raw_request("tools/call", None)
            await crec.notified.wait()
        assert crec.requests == [("sampling/createMessage", {"x": 1})]
        assert crec.notifications == [("notifications/message", {"level": "info"})]
        assert result["sample"] == {"echoed": "sampling/createMessage", "params": {"x": 1}}


@pytest.mark.anyio
async def test_base_context_report_progress_invokes_caller_on_progress():
    received: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        received.append((progress, total, message))

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        bctx = BaseContext(ctx)
        await bctx.report_progress(0.5, total=1.0, message="halfway")
        return {}

    async with running_pair(direct_pair, server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5):
            await client.send_raw_request("t", None, {"on_progress": on_progress})
        assert received == [(0.5, 1.0, "halfway")]


@pytest.mark.anyio
async def test_base_context_satisfies_outbound_so_peer_mixin_works():
    """Wrapping a BaseContext in Peer proves it satisfies Outbound structurally."""

    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        bctx = BaseContext(ctx)
        await Peer(bctx).ping()
        return {}

    crec = Recorder()
    c_req, c_notify = echo_handlers(crec)
    async with running_pair(
        direct_pair, server_on_request=server_on_request, client_on_request=c_req, client_on_notify=c_notify
    ) as (client, *_):
        with anyio.fail_after(5):
            await client.send_raw_request("t", None)
        assert crec.requests == [("ping", None)]


@pytest.mark.anyio
async def test_base_context_meta_holds_supplied_request_params_meta():
    async def server_on_request(ctx: DCtx, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        bctx = BaseContext(ctx, meta={"progressToken": "abc"})
        assert bctx.meta is not None and bctx.meta.get("progressToken") == "abc"
        return {}

    async with running_pair(direct_pair, server_on_request=server_on_request) as (client, *_):
        with anyio.fail_after(5):
            await client.send_raw_request("t", None)
