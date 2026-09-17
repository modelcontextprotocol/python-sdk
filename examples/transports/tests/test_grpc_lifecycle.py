"""Live cancellation and shutdown checks that require the current gRPC server to execute."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import anyio.abc
import grpc.aio
import pytest
from mcp import Client, MCPError
from mcp.server.mcpserver import MCPServer
from mcp.types import CONNECTION_CLOSED, REQUEST_TIMEOUT

from mcp_transport_examples.grpc import grpc_client, grpc_server


async def verify(cause: str) -> None:
    entered = anyio.Event()
    cancelled = anyio.Event()
    stop = anyio.Event()
    stopped = anyio.Event()
    finished = anyio.Event()
    errors: list[int] = []

    @asynccontextmanager
    async def lifespan(server: MCPServer[None]) -> AsyncIterator[None]:
        try:
            yield None
        finally:
            assert cancelled.is_set()

    server = MCPServer("gRPC cancellation", lifespan=lifespan)

    @server.tool()
    async def wait() -> str:
        entered.set()
        try:
            await anyio.sleep_forever()
        finally:
            cancelled.set()
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
            stopped.set()

    async with anyio.create_task_group() as tg:
        await tg.start(run_server)
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            async with Client(grpc_client(channel), mode="2026-07-28") as client:

                async def call(*, task_status: anyio.abc.TaskStatus[anyio.CancelScope]) -> None:
                    with anyio.CancelScope() as scope:
                        task_status.started(scope)
                        try:
                            # A real deadline is the behavior under test, not a synchronization delay.
                            await client.call_tool("wait", read_timeout_seconds=0.5 if cause == "timeout" else None)
                        except MCPError as exc:
                            errors.append(exc.code)
                    finished.set()

                async with anyio.create_task_group() as calls:
                    scope = await calls.start(call)
                    await entered.wait()
                    if cause == "caller":
                        scope.cancel()
                    elif cause == "runtime":
                        stop.set()
                    elif cause == "channel":
                        await channel.close()
                    await finished.wait()
                    await cancelled.wait()
                expected = [] if cause == "caller" else [REQUEST_TIMEOUT if cause == "timeout" else CONNECTION_CLOSED]
                assert errors == expected
            stop.set()
            await stopped.wait()


@pytest.mark.anyio
@pytest.mark.parametrize("cause", ["caller", "timeout", "runtime", "channel"])
async def test_native_cancellation_finishes_the_request_and_handler(cause: str) -> None:
    """Exercise this process's gRPC server, not a recorded response or an external service."""
    with anyio.fail_after(5):
        await verify(cause)
