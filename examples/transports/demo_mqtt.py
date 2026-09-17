"""Exercise the MQTT 5 adapter against the local Mosquitto broker."""

import os
from contextlib import AsyncExitStack

import aiomqtt
import anyio
from mcp.shared.transport import Transport

from demo_common import verify
from mcp_transport_examples.mqtt import mqtt_transport


async def open_transport(stack: AsyncExitStack, principal: str, session: str, server_side: bool) -> Transport:
    user = "server" if server_side else principal
    client = await stack.enter_async_context(
        aiomqtt.Client(
            "127.0.0.1",
            int(os.environ.get("MQTT_TEST_PORT", "13883")),
            username=user,
            password=f"test-{user}-password",
            protocol=aiomqtt.ProtocolVersion.V5,
            max_queued_incoming_messages=256,
        )
    )
    topic = f"mcp/{principal}/{session}"
    incoming, outgoing = ("requests", "responses") if server_side else ("responses", "requests")
    return mqtt_transport(client, incoming_topic=f"{topic}/{incoming}", outgoing_topic=f"{topic}/{outgoing}")


async def main() -> None:
    for highlevel in (False, True):
        for mode in ("legacy", "auto", "2026-07-28"):
            with anyio.fail_after(5):
                await verify(open_transport, kind="mqtt", highlevel=highlevel, mode=mode)


if __name__ == "__main__":
    anyio.run(main)
