"""
In-memory transports
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp_python.client.session import ClientSession
from mcp_python.server import Server
from mcp_python.types import JSONRPCMessage

MessageStream = tuple[
    MemoryObjectReceiveStream[JSONRPCMessage | Exception],
    MemoryObjectSendStream[JSONRPCMessage]
]

@asynccontextmanager
async def create_client_server_memory_streams() -> AsyncGenerator[
    tuple[MessageStream, MessageStream],
    None
]:
    """
    Creates a pair of bidirectional memory streams for client-server communication.

    Returns:
        A tuple of (client_streams, server_streams) where each is a tuple of
        (read_stream, write_stream)
    """
    # Create streams for both directions
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[
        JSONRPCMessage | Exception
    ](1)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[
        JSONRPCMessage | Exception
    ](1)

    client_streams = (server_to_client_receive, client_to_server_send)
    server_streams = (client_to_server_receive, server_to_client_send)

    async with (
        server_to_client_receive,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
    ):
        yield client_streams, server_streams


@asynccontextmanager
async def create_connected_server_and_client_session(
    server: Server,
) -> AsyncGenerator[ClientSession, None]:
    """Creates a ServerSession that is connected to the `server`."""
    async with create_client_server_memory_streams() as (
        client_streams,
        server_streams,
    ):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        # Create a cancel scope for the server task
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                server.run,
                server_read,
                server_write,
                server.create_initialization_options(),
            )

            try:
                # Client session could be created here using client_read and
                # client_write This would allow testing the server with a client
                # in the same process
                async with ClientSession(
                    read_stream=client_read, write_stream=client_write
                ) as client_session:
                    await client_session.initialize()
                    yield client_session
            finally:
                tg.cancel_scope.cancel()
