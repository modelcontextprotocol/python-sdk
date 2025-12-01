"""
MCP Proxy Module

This module provides utilities for proxying messages between two MCP transports,
enabling bidirectional message forwarding with proper error handling and cleanup.
"""

import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)

MessageStream = tuple[
    MemoryObjectReceiveStream[SessionMessage | Exception],
    MemoryObjectSendStream[SessionMessage],
]


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

    async def forward_to_server():
        """Forward messages from client to server."""
        try:
            async with client_read:
                async for message in client_read:
                    try:
                        # Forward SessionMessage objects directly
                        if isinstance(message, SessionMessage):
                            await server_write.send(message)
                        # Handle Exception objects via error callback
                        elif isinstance(message, Exception):
                            logger.debug(f"Exception received from client: {message}")
                            if onerror:
                                try:
                                    result = onerror(message)
                                    if isinstance(result, Awaitable):
                                        await result
                                except Exception as callback_error:  # pragma: no cover
                                    logger.exception("Error in onerror callback", exc_info=callback_error)
                            # Exceptions are not forwarded as messages (write streams only accept SessionMessage)
                    except anyio.ClosedResourceError:
                        logger.debug("Server write stream closed while forwarding from client")
                        break
                    except Exception as exc:  # pragma: no cover
                        logger.exception("Error forwarding message from client to server", exc_info=exc)
                        if onerror:
                            try:
                                result = onerror(exc)
                                if isinstance(result, Awaitable):
                                    await result
                            except Exception as callback_error:  # pragma: no cover
                                logger.exception("Error in onerror callback", exc_info=callback_error)
        except anyio.ClosedResourceError:
            logger.debug("Client read stream closed")
        except Exception as exc:  # pragma: no cover
            logger.exception("Error in forward_to_server task", exc_info=exc)
            if onerror:
                try:
                    result = onerror(exc)
                    if isinstance(result, Awaitable):
                        await result
                except Exception as callback_error:  # pragma: no cover
                    logger.exception("Error in onerror callback", exc_info=callback_error)
        finally:
            # Close server write stream when client read closes
            try:
                await server_write.aclose()
            except Exception:  # pragma: no cover
                # Stream might already be closed
                pass

    async def forward_to_client():
        """Forward messages from server to client."""
        try:
            async with server_read:
                async for message in server_read:
                    try:
                        # Forward SessionMessage objects directly
                        if isinstance(message, SessionMessage):
                            await client_write.send(message)
                        # Handle Exception objects via error callback
                        elif isinstance(message, Exception):
                            logger.debug(f"Exception received from server: {message}")
                            if onerror:
                                try:
                                    result = onerror(message)
                                    if isinstance(result, Awaitable):
                                        await result
                                except Exception as callback_error:  # pragma: no cover
                                    logger.exception("Error in onerror callback", exc_info=callback_error)
                            # Exceptions are not forwarded as messages (write streams only accept SessionMessage)
                    except anyio.ClosedResourceError:
                        logger.debug("Client write stream closed while forwarding from server")
                        break
                    except Exception as exc:  # pragma: no cover
                        logger.exception("Error forwarding message from server to client", exc_info=exc)
                        if onerror:
                            try:
                                result = onerror(exc)
                                if isinstance(result, Awaitable):
                                    await result
                            except Exception as callback_error:  # pragma: no cover
                                logger.exception("Error in onerror callback", exc_info=callback_error)
        except anyio.ClosedResourceError:
            logger.debug("Server read stream closed")
        except Exception as exc:  # pragma: no cover
            logger.exception("Error in forward_to_client task", exc_info=exc)
            if onerror:
                try:
                    result = onerror(exc)
                    if isinstance(result, Awaitable):
                        await result
                except Exception as callback_error:  # pragma: no cover
                    logger.exception("Error in onerror callback", exc_info=callback_error)
        finally:
            # Close client write stream when server read closes
            try:
                await client_write.aclose()
            except Exception:  # pragma: no cover
                # Stream might already be closed
                pass

    async with anyio.create_task_group() as tg:
        tg.start_soon(forward_to_server)
        tg.start_soon(forward_to_client)
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
