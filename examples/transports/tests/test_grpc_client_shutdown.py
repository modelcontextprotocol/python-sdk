"""Client shutdown must interrupt callbacks as well as gRPC socket reads."""

import anyio
import anyio.abc
import grpc.aio
import pytest
from mcp import Client, MCPError
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CONNECTION_CLOSED

from mcp_transport_examples.grpc import grpc_client, grpc_server


async def verify(*, shield_cleanup: bool = False) -> None:
    cleanup_started = anyio.Event()
    release_cleanup = anyio.Event()
    callback_entered = anyio.Event()
    callback_cancelled = anyio.Event()
    close_client = anyio.Event()
    client_closed = anyio.Event()
    call_finished = anyio.Event()
    server_cancelled = anyio.Event()
    server = MCPServer("client shutdown")

    @server.tool()
    async def wait(ctx: Context) -> str:
        try:
            await ctx.report_progress(1, 2)
            await anyio.sleep_forever()
        finally:
            server_cancelled.set()
        raise NotImplementedError

    async def progress(progress: float, total: float | None, message: str | None) -> None:
        callback_entered.set()
        try:
            await anyio.sleep_forever()
        finally:
            if shield_cleanup:
                with anyio.CancelScope(shield=True):
                    cleanup_started.set()
                    await release_cleanup.wait()
            callback_cancelled.set()

    listener = grpc.aio.server()
    port = listener.add_insecure_port("127.0.0.1:0")
    try:
        async with server.serve() as runtime:
            await runtime.connect(grpc_server(listener))
            await listener.start()
            async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:

                async def own_client(*, task_status: anyio.abc.TaskStatus[Client]) -> None:
                    async with Client(grpc_client(channel), mode="2026-07-28") as client:
                        task_status.started(client)
                        await close_client.wait()
                    client_closed.set()

                async def call(client: Client) -> None:
                    with pytest.raises(MCPError) as exc:
                        await client.call_tool("wait", progress_callback=progress)
                    assert exc.value.code == CONNECTION_CLOSED
                    call_finished.set()

                async with anyio.create_task_group() as tg:
                    client = await tg.start(own_client)
                    tg.start_soon(call, client)
                    try:
                        await callback_entered.wait()
                        close_client.set()
                        if shield_cleanup:
                            await cleanup_started.wait()
                            # Shutdown must wait for this callback, not abandon it after five seconds.
                            with anyio.move_on_after(5.1) as window:
                                await client_closed.wait()
                            assert window.cancelled_caught
                    finally:
                        release_cleanup.set()
                    await client_closed.wait()
                    await call_finished.wait()
                    await server_cancelled.wait()
                assert callback_cancelled.is_set()
    finally:
        with anyio.move_on_after(5, shield=True):
            await listener.stop(0)


@pytest.mark.anyio
@pytest.mark.parametrize("shield_cleanup", [False, True])
async def test_client_shutdown_joins_blocked_callbacks(shield_cleanup: bool) -> None:
    """The client must wait for callback cleanup before relinquishing its session resources."""
    # The shielded case deliberately exceeds the former five-second join deadline.
    with anyio.fail_after(10):
        await verify(shield_cleanup=shield_cleanup)
