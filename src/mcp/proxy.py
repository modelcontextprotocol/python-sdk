"""Provide utilities for proxying messages between two MCP transports."""

from __future__ import annotations

import contextvars
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import partial
from typing import Any, Protocol, cast

import anyio
from anyio import to_thread

from mcp.shared._callable_inspection import is_async_callable
from mcp.shared._stream_protocols import ReadStream, WriteStream
from mcp.shared.message import SessionMessage

MessageStream = tuple[ReadStream[SessionMessage | Exception], WriteStream[SessionMessage]]
ErrorHandler = Callable[[Exception], None | Awaitable[None]]


class ContextualWriteStream(Protocol):
    async def send_with_context(self, context: contextvars.Context, item: SessionMessage | Exception) -> None: ...


@asynccontextmanager
async def mcp_proxy(
    transport_to_client: MessageStream,
    transport_to_server: MessageStream,
    *,
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
                        raise item

                    try:
                        await _forward_message(item, write_stream, read_stream)
                    except anyio.ClosedResourceError:
                        break
    except anyio.ClosedResourceError:
        return


async def _forward_message(
    item: SessionMessage,
    write_stream: WriteStream[SessionMessage],
    read_stream: ReadStream[SessionMessage | Exception],
) -> None:
    sender_context: contextvars.Context | None = getattr(read_stream, "last_context", None)
    context_write_stream = cast(ContextualWriteStream | None, _get_contextual_write_stream(write_stream))

    if sender_context is not None and context_write_stream is not None:
        await context_write_stream.send_with_context(sender_context, item)
        return

    await write_stream.send(item)


def _get_contextual_write_stream(write_stream: WriteStream[SessionMessage]) -> Any:
    send_with_context = getattr(write_stream, "send_with_context", None)
    if callable(send_with_context):
        return write_stream
    return None


async def _run_error_handler(error: Exception, on_error: ErrorHandler | None) -> None:
    if on_error is None:
        return

    try:
        if is_async_callable(on_error):
            await cast(Awaitable[None], on_error(error))
        else:
            await to_thread.run_sync(partial(on_error, error))
    except Exception:
        return
