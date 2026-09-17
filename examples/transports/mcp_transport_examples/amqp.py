"""A symmetric AMQP 0.9.1 transport for one logical MCP peer."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from types import TracebackType

import anyio
from aio_pika import Message
from aio_pika.abc import AbstractChannel, AbstractExchange, AbstractIncomingMessage
from aio_pika.exceptions import AMQPError, ChannelInvalidStateError
from anyio.streams.memory import MemoryObjectSendStream
from mcp.shared.transport import SessionMessage, TransportStreams
from mcp.types import jsonrpc_message_adapter
from pamqp.commands import Basic
from pydantic import ValidationError
from typing_extensions import Self


@asynccontextmanager
async def amqp_transport(
    channel: AbstractChannel,
    *,
    incoming_queue: str,
    outgoing_queue: str,
    expiry: int = 60,
    max_message_size: int = 4 * 1024 * 1024,
) -> AsyncIterator[TransportStreams]:
    """Connect a peer over two dedicated queues without automatic replay.

    You own `channel` and its connection. Use a fresh queue pair for every
    logical connection, provisioned and bound by a trusted account before
    entering the transport. Each queue receives through its own `.exchange`
    direct exchange. Clients need only publish/consume permissions, not topology
    configuration or binding rights. `expiry` controls outgoing message TTL.
    Messages are acknowledged before SDK handoff; redeliveries are rejected.
    This avoids automatically repeating side effects but can lose work after
    acknowledgment. A publisher confirmation is not tool completion. Keep the
    exchanges alive until both peers exit. Remote loss while idle is not
    detected automatically; configure MCP request timeouts and supervise idle
    sessions separately.

    Raises:
        ValueError: If an encoded outgoing message exceeds `max_message_size`.
        AMQPError: If consumption fails.
        anyio.BrokenResourceError: If publication fails or is returned as unroutable.
    """
    if not incoming_queue or not outgoing_queue or incoming_queue == outgoing_queue:
        raise ValueError("AMQP directions must use different nonempty queue names")
    if expiry < 1 or max_message_size < 1 or not channel.publisher_confirms:
        raise ValueError("Positive limits and publisher confirmations are required")
    incoming = await channel.get_queue(incoming_queue, ensure=False)
    outgoing_exchange = await channel.get_exchange(f"{outgoing_queue}.exchange", ensure=False)
    await channel.set_qos(prefetch_count=16)
    send, receive = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    writer = _AMQPWriter(outgoing_exchange, outgoing_queue, expiry, max_message_size, send)

    lock = anyio.Lock()
    active: set[anyio.Event] = set()

    def channel_closed(sender: object, exc: BaseException | None) -> None:
        writer.closed = True
        send.close()

    async def deliver(message: AbstractIncomingMessage) -> None:
        finished = anyio.Event()
        active.add(finished)
        try:
            async with lock:
                if message.redelivered:
                    await message.reject(requeue=False)
                    await send.send(ValueError("AMQP redelivery is not replayed"))
                    return
                await message.ack()
                if len(message.body) > max_message_size or message.content_type != "application/json":
                    await send.send(ValueError("Rejected oversized or non-JSON AMQP message"))
                    return
                if not message.body:
                    writer.closed = True
                    send.close()
                    return
                try:
                    decoded = jsonrpc_message_adapter.validate_json(message.body, by_name=False)
                except ValidationError as exc:
                    await send.send(exc)
                else:
                    await send.send(SessionMessage(decoded))
        except (AMQPError, ChannelInvalidStateError):
            send.close()
        except (anyio.BrokenResourceError, anyio.ClosedResourceError):
            pass
        finally:
            active.remove(finished)
            finished.set()

    async with send, receive:
        channel.close_callbacks.add(channel_closed)
        try:
            tag = await incoming.consume(deliver, exclusive=True)
            try:
                async with writer:
                    yield receive, writer
            finally:
                send.close()
                with anyio.move_on_after(1, shield=True), suppress(AMQPError, ChannelInvalidStateError):
                    await incoming.cancel(tag)
                    for finished in tuple(active):
                        await finished.wait()
        finally:
            channel.close_callbacks.discard(channel_closed)


@dataclass
class _AMQPWriter:
    exchange: AbstractExchange
    queue: str
    expiry: int
    max_message_size: int
    inbound: MemoryObjectSendStream[SessionMessage | Exception]
    closed: bool = False

    async def send(self, item: SessionMessage, /) -> None:
        if self.closed:
            raise anyio.ClosedResourceError
        payload = item.message.model_dump_json(by_alias=True, exclude_none=True).encode()
        if len(payload) > self.max_message_size:
            raise ValueError("Encoded MCP message exceeds max_message_size")
        await self._publish(payload)

    async def aclose(self) -> None:
        if not self.closed:
            self.closed = True
            with anyio.move_on_after(1, shield=True), suppress(anyio.BrokenResourceError):
                await self._publish(b"")

    async def _publish(self, payload: bytes) -> None:
        try:
            confirmation = await self.exchange.publish(
                Message(payload, content_type="application/json", expiration=self.expiry),
                routing_key=self.queue,
                mandatory=True,
            )
            if not isinstance(confirmation, Basic.Ack):
                raise anyio.BrokenResourceError("AMQP publication was not acknowledged")
        except (AMQPError, ChannelInvalidStateError, anyio.BrokenResourceError) as exc:
            self.closed = True
            self.inbound.close()
            raise anyio.BrokenResourceError("AMQP publication failed") from exc

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        await self.aclose()
