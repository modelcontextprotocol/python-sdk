import multiprocessing
import socket
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

import pytest
import uvicorn
from anyio.streams.memory import MemoryObjectSendStream
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

import mcp.shared.memory
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCNotification, JSONRPCRequest
from tests.test_helpers import wait_for_server


def run_server(port: int) -> None:  # pragma: no cover
    """Run server with SSE and Streamable HTTP endpoints."""
    server = Server(name="cleanup_test_server")
    session_manager = StreamableHTTPSessionManager(app=server, json_response=False)
    sse_transport = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> Response:
        async with sse_transport.connect_sse(request.scope, request.receive, request._send) as streams:
            if streams:
                await server.run(streams[0], streams[1], server.create_initialization_options())
        return Response()

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        async with session_manager.run():
            yield

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse_transport.handle_post_message),
            Mount("/mcp", app=session_manager.handle_request),
        ],
        lifespan=lifespan,
    )
    uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")).run()


@pytest.fixture
def server_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def test_server(server_port: int) -> Generator[str, None, None]:
    """Start server with SSE and Streamable HTTP endpoints."""
    proc = multiprocessing.Process(target=run_server, kwargs={"port": server_port}, daemon=True)
    proc.start()
    wait_for_server(server_port)
    try:
        yield f"http://127.0.0.1:{server_port}"
    finally:
        proc.terminate()
        proc.join(timeout=2)
        if proc.is_alive():  # pragma: no cover
            proc.kill()
            proc.join(timeout=1)


@pytest.fixture
def sse_server_url(test_server: str) -> str:
    return f"{test_server}/sse"


@pytest.fixture
def streamable_server_url(test_server: str) -> str:
    return f"{test_server}/mcp"


class SpyMemoryObjectSendStream:
    def __init__(self, original_stream: MemoryObjectSendStream[SessionMessage]):
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
        """Clear all captured messages."""
        self.client.sent_messages.clear()
        self.server.sent_messages.clear()

    def get_client_requests(self, method: str | None = None) -> list[JSONRPCRequest]:  # pragma: no cover
        """Get client-sent requests, optionally filtered by method."""
        return [
            req.message.root
            for req in self.client.sent_messages
            if isinstance(req.message.root, JSONRPCRequest) and (method is None or req.message.root.method == method)
        ]

    def get_server_requests(self, method: str | None = None) -> list[JSONRPCRequest]:  # pragma: no cover
        """Get server-sent requests, optionally filtered by method."""
        return [  # pragma: no cover
            req.message.root
            for req in self.server.sent_messages
            if isinstance(req.message.root, JSONRPCRequest) and (method is None or req.message.root.method == method)
        ]

    def get_client_notifications(self, method: str | None = None) -> list[JSONRPCNotification]:  # pragma: no cover
        """Get client-sent notifications, optionally filtered by method."""
        return [
            notif.message.root
            for notif in self.client.sent_messages
            if isinstance(notif.message.root, JSONRPCNotification)
            and (method is None or notif.message.root.method == method)
        ]

    def get_server_notifications(self, method: str | None = None) -> list[JSONRPCNotification]:  # pragma: no cover
        """Get server-sent notifications, optionally filtered by method."""
        return [
            notif.message.root
            for notif in self.server.sent_messages
            if isinstance(notif.message.root, JSONRPCNotification)
            and (method is None or notif.message.root.method == method)
        ]


@pytest.fixture
def stream_spy() -> Generator[Callable[[], StreamSpyCollection], None, None]:
    """Fixture that provides spies for both client and server write streams.

    Example usage:
        async def test_something(stream_spy):
            # ... set up server and client ...

            spies = stream_spy()

            # Run some operation that sends messages
            await client.some_operation()

            # Check the messages
            requests = spies.get_client_requests(method="some/method")
            assert len(requests) == 1

            # Clear for the next operation
            spies.clear()
    """
    client_spy = None
    server_spy = None

    # Store references to our spy objects
    def capture_spies(c_spy: SpyMemoryObjectSendStream, s_spy: SpyMemoryObjectSendStream):
        nonlocal client_spy, server_spy
        client_spy = c_spy
        server_spy = s_spy

    # Create patched version of stream creation
    original_create_streams = mcp.shared.memory.create_client_server_memory_streams

    @asynccontextmanager
    async def patched_create_streams():
        async with original_create_streams() as (client_streams, server_streams):
            client_read, client_write = client_streams
            server_read, server_write = server_streams

            # Create spy wrappers
            spy_client_write = SpyMemoryObjectSendStream(client_write)
            spy_server_write = SpyMemoryObjectSendStream(server_write)

            # Capture references for the test to use
            capture_spies(spy_client_write, spy_server_write)

            yield (client_read, spy_client_write), (server_read, spy_server_write)

    # Apply the patch for the duration of the test
    with patch("mcp.shared.memory.create_client_server_memory_streams", patched_create_streams):
        # Return a collection with helper methods
        def get_spy_collection() -> StreamSpyCollection:
            assert client_spy is not None, "client_spy was not initialized"
            assert server_spy is not None, "server_spy was not initialized"
            return StreamSpyCollection(client_spy, server_spy)

        yield get_spy_collection
