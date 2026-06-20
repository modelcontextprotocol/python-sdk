"""In-memory transport for testing MCP servers without network overhead."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from types import TracebackType
from typing import Any

import anyio

from mcp.client._transport import TransportStreams
from mcp.server import Server
from mcp.server.mcpserver import MCPServer
from mcp.shared.memory import create_client_server_memory_streams

SERVER_SHUTDOWN_GRACE = 2.0
"""Seconds to wait for the in-process server to exit on EOF before cancelling."""


class InMemoryTransport:
    """In-memory transport for testing MCP servers without network overhead.

    This transport starts the server in a background task and provides
    streams for client-side communication. The server is automatically
    stopped when the context manager exits.
    """

    def __init__(self, server: Server[Any] | MCPServer, *, raise_exceptions: bool = False) -> None:
        """Initialize the in-memory transport.

        Args:
            server: The MCP server to connect to (Server or MCPServer instance)
            raise_exceptions: Whether to raise exceptions from the server
        """
        self._server = server
        self._raise_exceptions = raise_exceptions
        self._cm: AbstractAsyncContextManager[TransportStreams] | None = None

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[TransportStreams]:
        """Connect to the server and yield streams for communication."""
        # Unwrap MCPServer to get underlying Server
        if isinstance(self._server, MCPServer):
            # TODO(Marcelo): Make `lowlevel_server` public.
            actual_server: Server[Any] = self._server._lowlevel_server  # type: ignore[reportPrivateUsage]
        else:
            actual_server = self._server

        async with create_client_server_memory_streams() as (client_streams, server_streams):
            client_read, client_write = client_streams
            server_read, server_write = server_streams

            server_done = anyio.Event()

            async def _run_server() -> None:
                try:
                    await actual_server.run(
                        server_read,
                        server_write,
                        actual_server.create_initialization_options(),
                        raise_exceptions=self._raise_exceptions,
                    )
                finally:
                    server_done.set()

            async with anyio.create_task_group() as tg:
                tg.start_soon(_run_server)

                try:
                    yield client_read, client_write
                finally:
                    # EOF the server (and our own read side) instead of
                    # cancelling outright. The dispatcher's run() cancels its
                    # own in-flight handlers on read-stream EOF, so for a
                    # well-behaved server the task exits naturally and the
                    # task-group join below is immediate. Cancelling here
                    # unconditionally would `coro.throw()` into this task,
                    # which on CPython 3.11 (gh-106749) drops `'call'` trace
                    # events for the outer await chain and desyncs coverage's
                    # CTracer past the test frame.
                    await client_write.aclose()
                    await server_write.aclose()
                    # Backstop: the dispatcher exits on EOF, but the server's
                    # own teardown (lifespan __aexit__, connection.exit_stack
                    # callbacks) runs after that and is user code. If it never
                    # completes the join would hang forever, so bound the wait
                    # and fall back to cancelling. The healthy path returns
                    # from wait() without the timeout firing, so the cancel is
                    # never reached and gh-106749 stays avoided. If the cancel
                    # does fire, the checkpoint at the end of
                    # `create_client_server_memory_streams` resyncs the tracer.
                    with anyio.move_on_after(SERVER_SHUTDOWN_GRACE):
                        await server_done.wait()
                    if not server_done.is_set():
                        tg.cancel_scope.cancel()

    async def __aenter__(self) -> TransportStreams:
        """Connect to the server and return streams for communication."""
        self._cm = self._connect()
        return await self._cm.__aenter__()

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """Close the transport and stop the server."""
        if self._cm is not None:  # pragma: no branch
            await self._cm.__aexit__(exc_type, exc_val, exc_tb)
            self._cm = None
