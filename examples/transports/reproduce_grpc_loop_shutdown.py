"""Reproduce late gRPC connectivity completions without importing the MCP SDK."""

import asyncio
import sys

import anyio
import anyio.abc
import grpc
import grpc.aio


def main() -> None:
    """Exit unsuccessfully when a native completion targets an earlier, closed loop."""
    channels: list[grpc.aio.Channel] = []
    errors: list[dict[str, object]] = []

    async def run() -> None:
        asyncio.get_running_loop().set_exception_handler(lambda loop, context: errors.append(context))
        channel = grpc.aio.insecure_channel("127.0.0.1:1")
        channels.append(channel)

        async def watch(*, task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
            task_status.started()
            await channel.wait_for_state_change(channel.get_state())

        async with anyio.create_task_group() as tg:
            await tg.start(watch)
            tg.cancel_scope.cancel()
        await channel.close()

    for _ in range(10):
        anyio.run(run)
    assert not errors, (grpc.__version__, sys.version, errors)


if __name__ == "__main__":
    main()
