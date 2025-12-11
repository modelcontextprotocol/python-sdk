"""Utilities for proxying messages between MCP transports."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp.shared.message import SessionMessage

MessageStream = tuple[
    MemoryObjectReceiveStream[SessionMessage | Exception],
    MemoryObjectSendStream[SessionMessage],
]


@asynccontextmanager
async def mcp_proxy(
    client_streams: MessageStream,
    server_streams: MessageStream,
    on_error: Callable[[Exception], None | Awaitable[None]] | None = None,
) -> AsyncGenerator[None, None]:
    """Proxy messages bidirectionally between two MCP transports.

    Sets up bidirectional message forwarding between two transport pairs.
    Messages from the client are forwarded to the server, and vice versa.
    When the context exits, both forwarding directions are cancelled.

    Args:
        client_streams: A tuple of (read_stream, write_stream) for the client side.
        server_streams: A tuple of (read_stream, write_stream) for the server side.
        on_error: Optional callback for handling exceptions received on streams.
            Can be sync or async. Called with the Exception object.

    Example:
        ```python
        async with mcp_proxy(
            client_streams=(client_read, client_write),
            server_streams=(server_read, server_write),
            on_error=lambda e: print(f"Error: {e}"),
        ):
            # Proxy is active, forwarding messages bidirectionally
            await some_operation()
        # Forwarding stops when exiting the context
        ```
    """
    client_read, client_write = client_streams
    server_read, server_write = server_streams

    async def forward(
        read: MemoryObjectReceiveStream[SessionMessage | Exception],
        write: MemoryObjectSendStream[SessionMessage],
    ) -> None:
        async for msg in read:
            if isinstance(msg, Exception):
                if on_error:
                    try:
                        result = on_error(msg)
                        if isinstance(result, Awaitable):
                            await result
                    except Exception:
                        pass  # Don't let callback errors crash the proxy
            else:
                try:
                    await write.send(msg)
                except (anyio.ClosedResourceError, anyio.BrokenResourceError):
                    return  # Destination closed, stop this direction

    async with anyio.create_task_group() as tg:
        tg.start_soon(forward, client_read, server_write)
        tg.start_soon(forward, server_read, client_write)
        try:
            yield
        finally:
            tg.cancel_scope.cancel()
