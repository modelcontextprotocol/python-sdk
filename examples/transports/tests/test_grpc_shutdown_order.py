"""Lifespan resources must outlive a handler performing shielded cleanup."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import anyio.abc
import grpc.aio
import pytest
from mcp import Client, MCPError
from mcp.server.mcpserver import MCPServer
from mcp.types import CONNECTION_CLOSED

from mcp_transport_examples.grpc import grpc_client, grpc_server


async def verify() -> None:
    entered = anyio.Event()
    cleanup_started = anyio.Event()
    release_cleanup = anyio.Event()
    cleanup_finished = anyio.Event()
    lifespan_closed = anyio.Event()
    stop = anyio.Event()

    @asynccontextmanager
    async def lifespan(server: MCPServer[None]) -> AsyncIterator[None]:
        try:
            yield None
        finally:
            lifespan_closed.set()
            assert cleanup_finished.is_set()

    server = MCPServer("shutdown order", lifespan=lifespan)

    @server.tool()
    async def wait() -> str:
        entered.set()
        try:
            await anyio.sleep_forever()
        finally:
            with anyio.CancelScope(shield=True):
                cleanup_started.set()
                await release_cleanup.wait()
                assert not lifespan_closed.is_set()
                cleanup_finished.set()
        raise NotImplementedError

    listener = grpc.aio.server()
    port = listener.add_insecure_port("127.0.0.1:0")

    async def run_server(*, task_status: anyio.abc.TaskStatus[None]) -> None:
        try:
            async with server.serve() as runtime:
                await runtime.connect(grpc_server(listener))
                await listener.start()
                task_status.started()
                await stop.wait()
        finally:
            with anyio.move_on_after(5, shield=True):
                await listener.stop(0)

    async with anyio.create_task_group() as tg:
        await tg.start(run_server)
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            async with Client(grpc_client(channel), mode="2026-07-28") as client:

                async def call() -> None:
                    with pytest.raises(MCPError) as exc:
                        await client.call_tool("wait")
                    assert exc.value.code == CONNECTION_CLOSED

                async with anyio.create_task_group() as calls:
                    calls.start_soon(call)
                    try:
                        await entered.wait()
                        stop.set()
                        await cleanup_started.wait()
                        # The old five-second join timeout closed lifespan while this cleanup still ran.
                        with anyio.move_on_after(5.1) as window:
                            await lifespan_closed.wait()
                        assert window.cancelled_caught
                    finally:
                        release_cleanup.set()
                    await lifespan_closed.wait()
            assert cleanup_finished.is_set()


@pytest.mark.anyio
async def test_runtime_keeps_lifespan_alive_through_shielded_handler_cleanup() -> None:
    """The live handler must finish using application state before lifespan releases it."""
    # This check intentionally holds cleanup past the old five-second deadline.
    with anyio.fail_after(10):
        await verify()
