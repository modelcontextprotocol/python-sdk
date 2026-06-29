from collections.abc import Callable, Generator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

import pytest
from mcp_types import JSONRPCNotification, JSONRPCRequest

import mcp.shared.memory
from mcp.client._transport import WriteStream
from mcp.shared.message import SessionMessage


class SpyMemoryObjectSendStream:
    def __init__(self, original_stream: WriteStream[SessionMessage]):
        self.original_stream = original_stream
        self.sent_messages: list[SessionMessage] = []

    async def send(self, message: SessionMessage):
        self.sent_messages.append(message)
        await self.original_stream.send(message)

    async def aclose(self):
        await self.original_stream.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: Any):
        await self.aclose()


class StreamSpyCollection:
    def __init__(self, client_spy: SpyMemoryObjectSendStream, server_spy: SpyMemoryObjectSendStream):
        self.client = client_spy
        self.server = server_spy

    def clear(self) -> None:
        self.client.sent_messages.clear()
        self.server.sent_messages.clear()

    def get_client_requests(self, method: str | None = None) -> list[JSONRPCRequest]:
        return [
            req.message
            for req in self.client.sent_messages
            if isinstance(req.message, JSONRPCRequest) and (method is None or req.message.method == method)
        ]

    def get_server_requests(self, method: str | None = None) -> list[JSONRPCRequest]:  # pragma: no cover
        return [  # pragma: no cover
            req.message
            for req in self.server.sent_messages
            if isinstance(req.message, JSONRPCRequest) and (method is None or req.message.method == method)
        ]

    def get_client_notifications(self, method: str | None = None) -> list[JSONRPCNotification]:  # pragma: no cover
        return [
            notif.message
            for notif in self.client.sent_messages
            if isinstance(notif.message, JSONRPCNotification) and (method is None or notif.message.method == method)
        ]

    def get_server_notifications(self, method: str | None = None) -> list[JSONRPCNotification]:  # pragma: no cover
        return [
            notif.message
            for notif in self.server.sent_messages
            if isinstance(notif.message, JSONRPCNotification) and (method is None or notif.message.method == method)
        ]


@pytest.fixture
def stream_spy() -> Generator[Callable[[], StreamSpyCollection], None, None]:
    """Patch memory stream creation so tests can inspect client- and server-sent messages.

    Call the yielded factory after the streams exist (i.e. once client/server are set up)
    to get a `StreamSpyCollection`.
    """
    client_spy = None
    server_spy = None

    def capture_spies(c_spy: SpyMemoryObjectSendStream, s_spy: SpyMemoryObjectSendStream):
        nonlocal client_spy, server_spy
        client_spy = c_spy
        server_spy = s_spy

    original_create_streams = mcp.shared.memory.create_client_server_memory_streams

    @asynccontextmanager
    async def patched_create_streams():
        async with original_create_streams() as (client_streams, server_streams):
            client_read, client_write = client_streams
            server_read, server_write = server_streams

            spy_client_write = SpyMemoryObjectSendStream(client_write)
            spy_server_write = SpyMemoryObjectSendStream(server_write)

            capture_spies(spy_client_write, spy_server_write)

            yield (client_read, spy_client_write), (server_read, spy_server_write)

    # Patch both locations since InMemoryTransport imports it directly
    with patch("mcp.shared.memory.create_client_server_memory_streams", patched_create_streams):
        with patch("mcp.client._memory.create_client_server_memory_streams", patched_create_streams):

            def get_spy_collection() -> StreamSpyCollection:
                assert client_spy is not None, "client_spy was not initialized"
                assert server_spy is not None, "server_spy was not initialized"
                return StreamSpyCollection(client_spy, server_spy)

            yield get_spy_collection
