"""Check RabbitMQ route isolation against the local broker fixture."""

import os
from uuid import uuid4

import aio_pika
import anyio
from aiormq.exceptions import ChannelAccessRefused


async def main() -> None:
    """Deny client topology changes and reply injection, including queue/exchange name collisions."""
    port = int(os.environ.get("AMQP_TEST_PORT", "15672"))
    with anyio.fail_after(5):
        async with await aio_pika.connect(
            host="127.0.0.1", port=port, login="server", password="test-server-password"
        ) as server:
            async with await server.channel() as setup:
                name = f"mcp.alice.{uuid4().hex}.responses"
                foreign_name = f"mcp.bob.{uuid4().hex}.requests"
                response_queue = await setup.declare_queue(name, auto_delete=True)
                foreign_queue = await setup.declare_queue(foreign_name, auto_delete=True)
                try:
                    response_exchange = await setup.declare_exchange(f"{name}.exchange", auto_delete=True)
                    foreign_exchange = await setup.declare_exchange(f"{foreign_name}.exchange", auto_delete=True)
                    await response_queue.bind(response_exchange, routing_key=name)
                    await foreign_queue.bind(foreign_exchange, routing_key=foreign_name)
                    async with await aio_pika.connect(
                        host="127.0.0.1", port=port, login="alice", password="test-alice-password"
                    ) as alice:
                        async with await alice.channel() as channel:
                            try:
                                await channel.declare_exchange(name, auto_delete=True)
                            except ChannelAccessRefused:
                                pass
                            else:
                                raise AssertionError(
                                    "Clients must not declare an exchange named after their response queue"
                                )

                        collision = await setup.declare_exchange(name, auto_delete=True)
                        await response_queue.bind(collision, routing_key=name)
                        async with await alice.channel() as channel:
                            queue = await channel.get_queue(name, ensure=False)
                            exchange = await channel.get_exchange(response_exchange.name, ensure=False)
                            try:
                                await queue.bind(exchange, routing_key=name)
                            except ChannelAccessRefused:
                                pass
                            else:
                                raise AssertionError("Clients must not modify response bindings")

                        for target, routing_key in (
                            ("", foreign_name),
                            (foreign_exchange.name, foreign_name),
                            (response_exchange.name, name),
                            (collision.name, name),
                        ):
                            async with await alice.channel(publisher_confirms=True) as channel:
                                destination = await channel.get_exchange(target, ensure=False)
                                try:
                                    await destination.publish(aio_pika.Message(b"forged"), routing_key=routing_key)
                                except ChannelAccessRefused:
                                    pass
                                else:
                                    raise AssertionError("Reply and cross-principal publication must be denied")
                    assert await response_queue.get(fail=False) is None
                    assert await foreign_queue.get(fail=False) is None
                finally:
                    with anyio.fail_after(5, shield=True):
                        await response_queue.delete()
                        await foreign_queue.delete()


if __name__ == "__main__":
    anyio.run(main)
