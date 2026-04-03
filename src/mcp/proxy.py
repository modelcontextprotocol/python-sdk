"""Provide utilities for proxying messages between two MCP transports."""

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

import anyio

from mcp.shared._stream_protocols import ReadStream, WriteStream
from mcp.shared.message import SessionMessage

MessageStream = tuple[ReadStream[SessionMessage | Exception], WriteStream[SessionMessage]]
ErrorHandler = Callable[[Exception], None | Awaitable[None]]


@asynccontextmanager
async def mcp_proxy(
    transport_to_client: MessageStream,
    transport_to_server: MessageStream,
    on_error: ErrorHandler | None = None,
) -> AsyncGenerator[None]:
    """Proxy messages bidirectionally between two MCP transports."""
    client_read, client_write = transport_to_client
    server_read, server_write = transport_to_server

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(_forward_messages, client_read, server_write, on_error)
        task_group.start_soon(_forward_messages, server_read, client_write, on_error)
        try:
            yield
        finally:
            task_group.cancel_scope.cancel()


async def _forward_messages(
    read_stream: ReadStream[SessionMessage | Exception],
    write_stream: WriteStream[SessionMessage],
    on_error: ErrorHandler | None,
) -> None:
    try:
        async with write_stream:
            async with read_stream:
                async for item in read_stream:
                    if isinstance(item, Exception):
                        await _run_error_handler(item, on_error)
                        continue

                    try:
                        await write_stream.send(item)
                    except anyio.ClosedResourceError:
                        break
    except anyio.ClosedResourceError:
        return


async def _run_error_handler(error: Exception, on_error: ErrorHandler | None) -> None:
    if on_error is None:
        return

    try:
        result = on_error(error)
        if inspect.isawaitable(result):
            await result
    except Exception:
        return
