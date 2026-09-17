"""Exercise the AMQP 0.9.1 adapter against the local RabbitMQ broker."""

import os
from contextlib import AsyncExitStack

import aio_pika
import anyio
from mcp.shared.transport import Transport

from demo_common import verify
from mcp_transport_examples.amqp import amqp_transport


async def open_transport(stack: AsyncExitStack, principal: str, session: str, server_side: bool) -> Transport:
    user = "server" if server_side else principal
    connection = await aio_pika.connect(
        host="127.0.0.1",
        port=int(os.environ.get("AMQP_TEST_PORT", "15672")),
        login=user,
        password=f"test-{user}-password",
    )
    await stack.enter_async_context(connection)
    channel = await connection.channel(publisher_confirms=True)
    stack.push_async_callback(channel.close)
    queue = f"mcp.{principal}.{session}"
    incoming, outgoing = ("requests", "responses") if server_side else ("responses", "requests")
    return amqp_transport(channel, incoming_queue=f"{queue}.{incoming}", outgoing_queue=f"{queue}.{outgoing}")


async def main() -> None:
    for highlevel in (False, True):
        for mode in ("legacy", "auto", "2026-07-28"):
            with anyio.fail_after(5):
                await verify(open_transport, kind="amqp", highlevel=highlevel, mode=mode)


if __name__ == "__main__":
    anyio.run(main)
