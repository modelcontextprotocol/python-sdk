"""
Socket Transport Server Module

This module implements a socket-based transport for MCP that provides
1-to-1 client-server communication over TCP sockets.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

import mcp.types as types
from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def socket_server(
    port: int,
    host: str = "127.0.0.1",
    encoding: str = "utf-8",
    encoding_error_handler: str = "strict",
) -> AsyncGenerator[
    tuple[
        MemoryObjectReceiveStream[SessionMessage | Exception],
        MemoryObjectSendStream[SessionMessage],
    ],
    None,
]:
    """
    Server transport for socket-based communication.

    This will connect to a client's TCP socket and communicate using
    JSON-RPC messages over the socket connection.

    Args:
        port: The port to connect to (required, must not be 0)
        host: The host to connect to (defaults to "127.0.0.1")
        encoding: Text encoding to use (defaults to "utf-8")
        encoding_error_handler: Text encoding error handler (defaults to "strict")

    Yields:
        A tuple containing:
        - read_stream: Stream for reading messages from the client
        - write_stream: Stream for sending messages to the client

    Raises:
        ValueError: If port is 0
    """
    if port == 0:
        raise ValueError(
            "Port cannot be 0 when connecting to client. A specific port must be provided."
        )

    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]

    write_stream: MemoryObjectSendStream[SessionMessage]
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    try:
        # Connect to the client's TCP server with retry logic
        stream = None
        for attempt in range(5):  # Try 5 times
            try:
                stream = await anyio.connect_tcp(host, port)
                logger.info(f"Connected to client at {host}:{port}")
                break
            except OSError as e:
                if attempt == 4:  # Last attempt
                    logger.error(f"Failed to connect to client at {host}:{port}")
                    raise e
                logger.info(f"Connection attempt {attempt + 1} failed, retrying...")
                await anyio.sleep(1)  # Wait a bit before retrying

        if not stream:
            raise RuntimeError("Failed to connect to client")

        async def socket_reader():
            """Reads messages from the socket and forwards them to read_stream."""
            try:
                async with read_stream_writer:
                    buffer = ""
                    async for data in stream:
                        text = data.decode(encoding, encoding_error_handler)
                        lines = (buffer + text).split("\n")
                        buffer = lines.pop()

                        for line in lines:
                            try:
                                message = types.JSONRPCMessage.model_validate_json(line)
                                session_message = SessionMessage(message)
                                await read_stream_writer.send(session_message)
                            except Exception as exc:
                                await read_stream_writer.send(exc)
                                continue
            except anyio.ClosedResourceError:
                await anyio.lowlevel.checkpoint()
            except anyio.get_cancelled_exc_class():
                # Handle cancellation gracefully
                logger.info("Socket reader cancelled")
                return
            except Exception as e:
                logger.error(f"Error in socket reader: {e}")
                raise
            finally:
                await stream.aclose()

        async def socket_writer():
            """Reads messages from write_stream and sends them over the socket."""
            try:
                async with write_stream_reader:
                    async for session_message in write_stream_reader:
                        json = session_message.message.model_dump_json(
                            by_alias=True, exclude_none=True
                        )
                        data = (json + "\n").encode(encoding, encoding_error_handler)
                        await stream.send(data)
            except anyio.ClosedResourceError:
                await anyio.lowlevel.checkpoint()
            except anyio.get_cancelled_exc_class():
                # Handle cancellation gracefully
                logger.info("Socket writer cancelled")
                return
            except Exception as e:
                logger.error(f"Error in socket writer: {e}")
                raise
            finally:
                await stream.aclose()

        async with anyio.create_task_group() as tg:
            tg.start_soon(socket_reader)
            tg.start_soon(socket_writer)

            try:
                yield read_stream, write_stream
            finally:
                # Cancel all tasks and clean up with timeout
                tg.cancel_scope.cancel()

                # Force cleanup with timeout to prevent hanging
                try:
                    with anyio.fail_after(5.0):  # 5 second timeout for cleanup
                        await stream.aclose()
                        await read_stream.aclose()
                        await write_stream.aclose()
                        await read_stream_writer.aclose()
                        await write_stream_reader.aclose()
                except anyio.get_cancelled_exc_class():
                    # If cleanup times out, log warning
                    logger.warning("Server cleanup timed out")

    except Exception:
        await read_stream.aclose()
        await write_stream.aclose()
        await read_stream_writer.aclose()
        await write_stream_reader.aclose()
        raise
