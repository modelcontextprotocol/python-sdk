"""A symmetric MQTT 5 transport for one logical MCP peer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from types import TracebackType

import aiomqtt
import anyio
from mcp.shared.transport import SessionMessage, TransportStreams
from mcp.types import jsonrpc_message_adapter
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from paho.mqtt.subscribeoptions import SubscribeOptions
from pydantic import ValidationError
from typing_extensions import Self


@asynccontextmanager
async def mqtt_transport(
    client: aiomqtt.Client,
    *,
    incoming_topic: str,
    outgoing_topic: str,
    expiry: int = 60,
    max_message_size: int = 4 * 1024 * 1024,
) -> AsyncIterator[TransportStreams]:
    """Connect one peer over two dedicated MQTT 5 topics using QoS 2.

    You own and enter `client`. Give each connection fresh topics, grant only
    its peer access through broker ACLs, and dedicate the client's messages
    iterator to this transport. Configure a QoS-2, non-retained Last Will with
    an empty payload on `outgoing_topic` before entering the client, and set a
    finite keepalive. The broker then closes the peer after connection loss;
    this adapter cannot add a Last Will to an already-connected client.
    Empty payloads close the logical connection.
    Retained messages are rejected; this adapter never reconnects or replays.

    Args:
        client: An entered MQTT 5 client with a bounded incoming queue.
        incoming_topic: Exact topic to receive from, without wildcards.
        outgoing_topic: Exact topic to publish to, without wildcards.
        expiry: Broker expiry for messages and the close signal, in seconds.
        max_message_size: Maximum encoded message size in either direction.

    Raises:
        ValueError: If the configuration is invalid or an outgoing message is too large.
        aiomqtt.MqttError: If subscription or publication fails.
    """
    aiomqtt.Topic(incoming_topic)
    aiomqtt.Topic(outgoing_topic)
    if incoming_topic == outgoing_topic:
        raise ValueError("MQTT directions must use different topics")
    if not 0 < expiry <= 2**32 - 1 or max_message_size < 1:
        raise ValueError("expiry must be a positive uint32 and max_message_size must be positive")
    properties = Properties(PacketTypes.PUBLISH)
    properties.MessageExpiryInterval = expiry
    writer = _MQTTWriter(client, outgoing_topic, properties, max_message_size)
    send, receive = anyio.create_memory_object_stream[SessionMessage | Exception](0)

    async def read_messages() -> None:
        async with send:
            try:
                async for message in client.messages:
                    if str(message.topic) != incoming_topic:
                        continue
                    if message.retain or message.qos != 2 or len(message.payload) > max_message_size:
                        await send.send(ValueError("Rejected retained, non-QoS-2, or oversized MQTT message"))
                        continue
                    if not message.payload:
                        break
                    try:
                        decoded = jsonrpc_message_adapter.validate_json(message.payload, by_name=False)
                    except ValidationError as exc:
                        await send.send(exc)
                    else:
                        await send.send(SessionMessage(decoded))
            except (aiomqtt.MqttError, anyio.BrokenResourceError, anyio.ClosedResourceError):
                pass

    try:
        await client.subscribe(
            incoming_topic, options=SubscribeOptions(qos=2, retainAsPublished=True, retainHandling=2)
        )
        async with receive, writer:
            async with anyio.create_task_group() as tg:
                tg.start_soon(read_messages)
                try:
                    yield receive, writer
                finally:
                    tg.cancel_scope.cancel()
    finally:
        await send.aclose()
        await receive.aclose()
        with anyio.move_on_after(1, shield=True), suppress(aiomqtt.MqttError):
            await client.unsubscribe(incoming_topic)


@dataclass
class _MQTTWriter:
    client: aiomqtt.Client
    topic: str
    properties: Properties
    max_message_size: int
    closed: bool = False

    async def send(self, item: SessionMessage, /) -> None:
        if self.closed:
            raise anyio.ClosedResourceError
        payload = item.message.model_dump_json(by_alias=True, exclude_none=True).encode()
        if len(payload) > self.max_message_size:
            raise ValueError("Encoded MCP message exceeds max_message_size")
        await self.client.publish(self.topic, payload, qos=2, retain=False, properties=self.properties)

    async def aclose(self) -> None:
        if not self.closed:
            self.closed = True
            with anyio.move_on_after(1, shield=True), suppress(aiomqtt.MqttError):
                await self.client.publish(self.topic, b"", qos=2, retain=False, properties=self.properties)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        await self.aclose()
