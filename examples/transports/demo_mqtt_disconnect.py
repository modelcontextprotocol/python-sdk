"""Check remote-peer loss using Mosquitto's session-takeover behavior."""

import os
from contextlib import AsyncExitStack
from uuid import uuid4

import aiomqtt
import anyio
from mcp import Client, MCPError
from mcp.server.mcpserver import MCPServer
from mcp.types import CONNECTION_CLOSED

from demo_mqtt import open_transport


async def main() -> None:
    """A broker-forced disconnect publishes the configured Last Will and settles a waiting MCP call."""
    entered = anyio.Event()
    finished = anyio.Event()
    server = MCPServer("peer loss")
    session = uuid4().hex

    @server.tool()
    async def hold() -> str:
        entered.set()
        await anyio.sleep_forever()
        raise NotImplementedError

    with anyio.fail_after(5):
        async with AsyncExitStack() as stack:
            server_transport = await open_transport(stack, "alice", session, True)
            client_transport = await open_transport(stack, "alice", session, False)
            runtime = await stack.enter_async_context(server.serve())
            await runtime.connect(server_transport)
            client = await stack.enter_async_context(Client(client_transport, read_timeout_seconds=None))

            async def call() -> None:
                try:
                    await client.call_tool("hold")
                except MCPError as exc:
                    assert exc.code == CONNECTION_CLOSED
                else:
                    raise AssertionError("Remote peer loss must fail the pending call")
                finished.set()

            async with anyio.create_task_group() as tg:
                tg.start_soon(call)
                await entered.wait()
                async with aiomqtt.Client(
                    "127.0.0.1",
                    int(os.environ.get("MQTT_TEST_PORT", "13883")),
                    username="bob",
                    password="test-bob-password",
                    identifier="server-alice",
                    protocol=aiomqtt.ProtocolVersion.V5,
                ):
                    assert [tool.name for tool in (await client.list_tools()).tools] == ["hold"]
                    assert not finished.is_set()
                async with aiomqtt.Client(
                    "127.0.0.1",
                    int(os.environ.get("MQTT_TEST_PORT", "13883")),
                    username="server-alice",
                    password="test-server-alice-password",
                    identifier="server-alice",
                    protocol=aiomqtt.ProtocolVersion.V5,
                ):
                    await finished.wait()


if __name__ == "__main__":
    anyio.run(main)
