"""In-memory transports"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import anyio.lowlevel

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
    # Callers routinely cancel a task group wrapped around these streams just
    # before this context exits; that cancel is delivered via `coro.throw()`,
    # which on CPython 3.11 (gh-106749) drops `'call'` trace events for the
    # outer await chain and desyncs coverage's CTracer past the caller's frame.
    # Closing memory streams never suspends, so this is the last chance to
    # resync: yielding once resumes via `.send()`, which re-stamps the missing
    # `'call'` events. Shielded so a pending outer cancel is not re-delivered.
    await anyio.lowlevel.cancel_shielded_checkpoint()
