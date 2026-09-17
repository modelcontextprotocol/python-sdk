"""A symmetric AMQP 0.9.1 transport for one logical MCP peer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from types import TracebackType

import anyio
from aio_pika import Message
from aio_pika.abc import AbstractChannel, AbstractIncomingMessage
from aio_pika.exceptions import AMQPError, ChannelInvalidStateError
from mcp.shared.transport import SessionMessage, TransportStreams
from mcp.types import jsonrpc_message_adapter
from pamqp.common import Arguments
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
    logical connection and restrict queue access with broker permissions.
    Messages are acknowledged before SDK handoff; redeliveries are rejected.
    This avoids automatically repeating side effects but can lose work after
    acknowledgment. A publisher confirmation is not tool completion.

    Raises:
        ValueError: If routing, limits, or publisher-confirm settings are invalid.
        AMQPError: If queue setup or publication fails.
    """
    if not incoming_queue or not outgoing_queue or incoming_queue == outgoing_queue:
        raise ValueError("AMQP directions must use different nonempty queue names")
    if expiry < 1 or max_message_size < 1 or not channel.publisher_confirms:
        raise ValueError("Positive limits and publisher confirmations are required")
    arguments: Arguments = {"x-expires": expiry * 1000, "x-max-length": 256, "x-overflow": "reject-publish"}
    incoming = await channel.declare_queue(incoming_queue, auto_delete=True, arguments=arguments)
    await channel.declare_queue(outgoing_queue, auto_delete=True, arguments=arguments)
    await channel.set_qos(prefetch_count=16)
    send, receive = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    writer = _AMQPWriter(channel, outgoing_queue, expiry, max_message_size)

    lock = anyio.Lock()
    active: set[anyio.Event] = set()

    def channel_closed(sender: object, exc: BaseException | None) -> None:
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
    channel: AbstractChannel
    queue: str
    expiry: int
    max_message_size: int
    closed: bool = False

    async def send(self, item: SessionMessage, /) -> None:
        if self.closed:
            raise anyio.ClosedResourceError
        payload = item.message.model_dump_json(by_alias=True, exclude_none=True).encode()
        if len(payload) > self.max_message_size:
            raise ValueError("Encoded MCP message exceeds max_message_size")
        await self.channel.default_exchange.publish(
            Message(payload, content_type="application/json", expiration=self.expiry), routing_key=self.queue
        )

    async def aclose(self) -> None:
        if not self.closed:
            self.closed = True
            with anyio.move_on_after(1, shield=True), suppress(AMQPError, ChannelInvalidStateError):
                await self.channel.default_exchange.publish(
                    Message(b"", content_type="application/json", expiration=self.expiry), routing_key=self.queue
                )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        await self.aclose()
