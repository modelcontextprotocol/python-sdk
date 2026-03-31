"""In-memory transports"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from mcp.shared._context_streams import ContextReceiveStream, ContextSendStream, create_context_streams
from mcp.shared.message import SessionMessage

MessageStream = tuple[ContextReceiveStream[SessionMessage | Exception], ContextSendStream[SessionMessage | Exception]]


@asynccontextmanager
async def create_client_server_memory_streams() -> AsyncGenerator[tuple[MessageStream, MessageStream], None]:
    """Creates a pair of bidirectional memory streams for client-server communication.

    Yields:
        A tuple of (client_streams, server_streams) where each is a tuple of
        (read_stream, write_stream)
    """
    # Create streams for both directions
    server_to_client_send, server_to_client_receive = create_context_streams[SessionMessage | Exception](1)
    client_to_server_send, client_to_server_receive = create_context_streams[SessionMessage | Exception](1)

    client_streams = (server_to_client_receive, client_to_server_send)
    server_streams = (client_to_server_receive, server_to_client_send)

    async with server_to_client_receive, client_to_server_send, client_to_server_receive, server_to_client_send:
        yield client_streams, server_streams
