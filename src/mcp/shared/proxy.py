"""
MCP Proxy Module

This module provides utilities for proxying messages between two MCP transports,
enabling bidirectional message forwarding with proper error handling and cleanup.
"""

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)

MessageStream = tuple[
    MemoryObjectReceiveStream[SessionMessage | Exception],
    MemoryObjectSendStream[SessionMessage],
]


async def _handle_error(
    error: Exception,
    onerror: Callable[[Exception], None | Awaitable[None]] | None,
) -> None:
    """Handle an error by calling the error callback if provided."""
    if onerror:
        try:
            result = onerror(error)
            if isinstance(result, Awaitable):
                await result
        except Exception as callback_error:  # pragma: no cover
            logger.exception("Error in onerror callback", exc_info=callback_error)


async def _forward_message(
    message: SessionMessage | Exception,
    write_stream: MemoryObjectSendStream[SessionMessage],
    onerror: Callable[[Exception], None | Awaitable[None]] | None,
    source: str,
) -> None:
    """Forward a single message, handling exceptions appropriately."""
    if isinstance(message, SessionMessage):
        await write_stream.send(message)
    elif isinstance(message, Exception):
        logger.debug(f"Exception received from {source}: {message}")
        await _handle_error(message, onerror)
        # Exceptions are not forwarded as messages (write streams only accept SessionMessage)


async def _forward_loop(
    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
    write_stream: MemoryObjectSendStream[SessionMessage],
    onerror: Callable[[Exception], None | Awaitable[None]] | None,
    source: str,
) -> None:
    """Forward messages from read_stream to write_stream."""
    try:
        async with read_stream:
            async for message in read_stream:
                try:
                    await _forward_message(message, write_stream, onerror, source)
                except anyio.ClosedResourceError:
                    logger.debug(f"{source} write stream closed")
                    break
                except Exception as exc:
                    logger.exception(f"Error forwarding message from {source}", exc_info=exc)
                    await _handle_error(exc, onerror)
    except anyio.ClosedResourceError:
        logger.debug(f"{source} read stream closed")
    except Exception as exc:
        logger.exception(f"Error in forward loop from {source}", exc_info=exc)
        await _handle_error(exc, onerror)
    finally:
        # Close write stream when read stream closes
        try:
            await write_stream.aclose()
        except Exception:  # pragma: no cover
            # Stream might already be closed
            pass


@asynccontextmanager
async def mcp_proxy(
    transport_to_client: MessageStream,
    transport_to_server: MessageStream,
    onerror: Callable[[Exception], None | Awaitable[None]] | None = None,
) -> AsyncGenerator[None, None]:
    """
    Proxy messages bidirectionally between two MCP transports.

    This function sets up bidirectional message forwarding between two transport pairs.
    When one transport closes, the other is also closed. Errors are forwarded to the
    error callback if provided.

    Args:
        transport_to_client: A tuple of (read_stream, write_stream) for the client-facing transport.
        transport_to_server: A tuple of (read_stream, write_stream) for the server-facing transport.
        onerror: Optional callback function for handling errors. Can be sync or async.
                Called with the Exception object when an error occurs.

    Example:
        ```python
        async with mcp_proxy(
            transport_to_client=(client_read, client_write),
            transport_to_server=(server_read, server_write),
            onerror=lambda e: logger.error(f"Proxy error: {e}"),
        ):
            # Proxy is active, forwarding messages bidirectionally
            await some_operation()
        # Both transports are closed when exiting the context
        ```

    Yields:
        None: The context manager yields control while the proxy is active.
    """
    client_read, client_write = transport_to_client
    server_read, server_write = transport_to_server

    async with anyio.create_task_group() as tg:
        tg.start_soon(_forward_loop, client_read, server_write, onerror, "client")
        tg.start_soon(_forward_loop, server_read, client_write, onerror, "server")
        try:
            yield
        finally:
            # Cancel the task group to stop forwarding
            tg.cancel_scope.cancel()
            # Close both write streams
            try:
                await client_write.aclose()
            except Exception:  # pragma: no cover
                pass
            try:
                await server_write.aclose()
            except Exception:  # pragma: no cover
                pass
