"""Check RabbitMQ route isolation against the local broker fixture."""

import os
from uuid import uuid4

import aio_pika
import anyio
from aiormq.exceptions import ChannelAccessRefused


async def main() -> None:
    """Reject default-exchange injection and publication to another principal's exchange."""
    port = int(os.environ.get("AMQP_TEST_PORT", "15672"))
    with anyio.fail_after(5):
        async with await aio_pika.connect(
            host="127.0.0.1", port=port, login="server", password="test-server-password"
        ) as server:
            async with await server.channel() as setup:
                name = f"mcp.bob.{uuid4().hex}.requests"
                queue = await setup.declare_queue(name, auto_delete=True)
                exchange = await setup.declare_exchange(f"{name}.exchange", auto_delete=True)
                await queue.bind(exchange, routing_key=name)
                try:
                    async with await aio_pika.connect(
                        host="127.0.0.1", port=port, login="alice", password="test-alice-password"
                    ) as alice:
                        for target in ("", exchange.name):
                            async with await alice.channel(publisher_confirms=True) as channel:
                                destination = await channel.get_exchange(target, ensure=False)
                                try:
                                    await destination.publish(aio_pika.Message(b"forged"), routing_key=name)
                                except ChannelAccessRefused:
                                    pass
                                else:
                                    raise AssertionError("Cross-principal publication must be denied")
                    assert await queue.get(fail=False) is None
                finally:
                    await queue.delete()


if __name__ == "__main__":
    anyio.run(main)
