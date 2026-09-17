"""Check AMQP close ordering, routing readiness, and the remote-loss timeout boundary."""

import os
from contextlib import AsyncExitStack
from uuid import uuid4

import aio_pika
import anyio
from mcp import Client, MCPError
from mcp.server.mcpserver import MCPServer
from mcp.shared.transport import SessionMessage
from mcp.types import CONNECTION_CLOSED, REQUEST_TIMEOUT, JSONRPCRequest

from demo_amqp import provision
from mcp_transport_examples.amqp import amqp_transport


async def main() -> None:
    """Exercise real broker behavior, including peer loss that requires a configured request deadline."""
    port = int(os.environ.get("AMQP_TEST_PORT", "15673"))
    for scenario in ("server-first", "client-first", "queued", "return", "raise-return", "peer-loss"):
        with anyio.fail_after(5):
            async with AsyncExitStack() as stack:
                owner = await stack.enter_async_context(
                    await aio_pika.connect(
                        host="127.0.0.1",
                        port=port,
                        login="server",
                        password="test-server-password",
                    )
                )
                setup = await owner.channel()
                stack.push_async_callback(setup.close)
                prefix = f"mcp.alice.{uuid4().hex}"
                await provision(stack, setup, prefix)
                server_connection = await stack.enter_async_context(
                    await aio_pika.connect(
                        host="127.0.0.1",
                        port=port,
                        login="server",
                        password="test-server-password",
                    )
                )
                client_connection = await stack.enter_async_context(
                    await aio_pika.connect(
                        host="127.0.0.1",
                        port=port,
                        login="alice",
                        password="test-alice-password",
                    )
                )
                server_channel = await server_connection.channel()
                stack.push_async_callback(server_channel.close)
                client_channel = await client_connection.channel(
                    publisher_confirms=True, on_return_raises=scenario != "return"
                )
                stack.push_async_callback(client_channel.close)
                server_transport = amqp_transport(
                    server_channel,
                    incoming_queue=f"{prefix}.requests",
                    outgoing_queue=f"{prefix}.responses",
                    expiry=120,
                )
                client_transport = amqp_transport(
                    client_channel,
                    incoming_queue=f"{prefix}.responses",
                    outgoing_queue=f"{prefix}.requests",
                )
                if scenario in ("server-first", "client-first"):
                    first, second = (
                        (server_transport, client_transport)
                        if scenario == "server-first"
                        else (client_transport, server_transport)
                    )
                    async with second as (receive, write):
                        async with first:
                            pass
                        try:
                            await receive.receive()
                        except anyio.EndOfStream:
                            pass
                        else:
                            raise AssertionError("The peer close must end the read stream")
                        try:
                            await write.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")))
                        except anyio.ClosedResourceError:
                            pass
                        else:
                            raise AssertionError("The peer close must also close the writer")
                elif scenario == "queued":
                    message = SessionMessage(
                        JSONRPCRequest(
                            jsonrpc="2.0",
                            id=1,
                            method="initialize",
                            params={
                                "protocolVersion": "2025-11-25",
                                "capabilities": {},
                                "clientInfo": {"name": "lifecycle", "version": "1"},
                            },
                        )
                    )
                    async with client_transport as (_, write):
                        await write.send(message)
                        async with server_transport as (read, _):
                            received = await read.receive()
                            assert isinstance(received, SessionMessage)
                            assert received.message == message.message
                elif scenario in ("return", "raise-return"):
                    queue = await setup.get_queue(f"{prefix}.requests", ensure=False)
                    exchange = await setup.get_exchange(f"{prefix}.requests.exchange", ensure=False)
                    await queue.unbind(exchange, routing_key=f"{prefix}.requests")
                    async with Client(client_transport, mode="2026-07-28") as client:
                        try:
                            await client.list_tools()
                        except MCPError as exc:
                            assert exc.code == CONNECTION_CLOSED
                        else:
                            raise AssertionError("An unroutable publish must fail immediately")
                else:
                    entered = anyio.Event()
                    finished = anyio.Event()
                    server = MCPServer("AMQP peer loss")

                    @server.tool()
                    async def hold() -> str:
                        entered.set()
                        await anyio.sleep_forever()
                        raise NotImplementedError

                    runtime = await stack.enter_async_context(server.serve())
                    await runtime.connect(server_transport)
                    # Remote-idle loss is not signalled by AMQP; the deadline is the behavior under test.
                    async with Client(client_transport, mode="2026-07-28", read_timeout_seconds=1) as client:

                        async def call() -> None:
                            try:
                                await client.call_tool("hold")
                            except MCPError as exc:
                                assert exc.code == REQUEST_TIMEOUT
                            else:
                                raise AssertionError("The remote-loss deadline must settle the request")
                            finished.set()

                        async with anyio.create_task_group() as tg:
                            tg.start_soon(call)
                            await entered.wait()
                            assert not finished.is_set()
                            await server_connection.close()
                            await finished.wait()
                assert not client_channel.is_closed
                await client_channel.set_qos(prefetch_count=16)
                if scenario != "peer-loss":
                    assert not server_channel.is_closed
                    await server_channel.set_qos(prefetch_count=16)


if __name__ == "__main__":
    anyio.run(main)
