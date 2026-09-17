"""Peer cancellation must be visible before the handler's cleanup runs."""

from collections.abc import Mapping
from typing import Any

import anyio
import anyio.abc
import grpc.aio
import pytest
from mcp import Client
from mcp.shared.dispatcher import DispatchContext
from mcp.shared.transport import TransportContext
from mcp.types import Request, RequestParams, Result

from mcp_transport_examples.grpc import grpc_client
from mcp_transport_examples.grpc_server import GRPCServerDispatcher


async def verify() -> None:
    entered = anyio.Event()
    done = anyio.Event()
    observed: list[bool] = []

    async def handle(
        ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        assert method == "example/wait"
        entered.set()
        try:
            await anyio.sleep_forever()
        finally:
            observed.append(ctx.cancel_requested.is_set())
            done.set()
        raise NotImplementedError

    async def notify(ctx: DispatchContext[TransportContext], method: str, params: Mapping[str, Any] | None) -> None:
        raise NotImplementedError

    listener = grpc.aio.server()
    port = listener.add_insecure_port("127.0.0.1:0")
    dispatcher = GRPCServerDispatcher(listener)
    try:
        async with anyio.create_task_group() as tg:
            await tg.start(dispatcher.run, handle, notify)
            await listener.start()
            async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                async with Client(grpc_client(channel), mode="2026-07-28") as client:

                    async def call(*, task_status: anyio.abc.TaskStatus[anyio.CancelScope]) -> None:
                        with anyio.CancelScope() as scope:
                            task_status.started(scope)
                            await client.session.send_request(
                                Request(method="example/wait", params=RequestParams()), Result
                            )

                    async with anyio.create_task_group() as calls:
                        scope = await calls.start(call)
                        await entered.wait()
                        scope.cancel()
                        await done.wait()
                assert observed == [True]
            tg.cancel_scope.cancel()
    finally:
        with anyio.move_on_after(5, shield=True):
            await listener.stop(0)


@pytest.mark.anyio
async def test_peer_cancellation_is_signalled_before_handler_cleanup() -> None:
    """Read cancel_requested during the live handler's cleanup, not after RPC completion."""
    with anyio.fail_after(5):
        await verify()
