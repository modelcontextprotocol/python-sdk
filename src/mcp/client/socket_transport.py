"""
Socket Transport Module

This module implements a socket-based transport for MCP that provides
1-to-1 client-server communication over TCP sockets.
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, TextIO

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import BaseModel, Field

import mcp.types as types
from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)


class SocketServerParameters(BaseModel):
    """Configuration parameters for socket-based transport."""

    command: str
    """The executable to run to start the server."""

    args: list[str] = Field(default_factory=list)
    """Command line arguments to pass to the executable."""

    env: dict[str, str] | None = None
    """
    The environment to use when spawning the process.
    If not specified, the current environment will be used.
    """

    cwd: str | Path | None = None
    """The working directory to use when spawning the process."""

    host: str = Field(default="127.0.0.1")
    """The host to bind to for socket communication."""

    port: int = Field(default=0)
    """
    The port to bind to for socket communication.
    If 0, a random available port will be used.
    """

    encoding: str = "utf-8"
    """The text encoding used when sending/receiving messages."""

    encoding_error_handler: str = "strict"
    """The text encoding error handler."""

    connection_timeout: float = Field(default=5.0)
    """Timeout in seconds for connection acceptance."""


@asynccontextmanager
async def socket_client(
    server: SocketServerParameters, errlog: TextIO = sys.stderr
) -> AsyncGenerator[
    tuple[
        MemoryObjectReceiveStream[SessionMessage | Exception],
        MemoryObjectSendStream[SessionMessage],
    ],
    None,
]:
    """
    Client transport for socket-based communication.

    This will:
    1. Start a server process using the provided command
    2. Create a socket connection to that server
    3. Communicate using JSON-RPC messages over the socket connection

    Args:
        server: Socket server parameters
        errlog: Where to send server process stderr (defaults to sys.stderr)

    Yields:
        A tuple containing:
        - read_stream: Stream for reading messages from the server
        - write_stream: Stream for sending messages to the server

    Raises:
        TimeoutError: If connection acceptance times out
        OSError: If process startup fails
        Exception: For other errors
    """
    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]

    write_stream: MemoryObjectSendStream[SessionMessage]
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    # Create a TCP listener first to get the port
    listener = await anyio.create_tcp_listener(
        local_host=server.host, local_port=server.port
    )
    actual_port = listener.extra(anyio.abc.SocketAttribute.local_port)
    logger.info(f"Listening on port {actual_port}")

    try:
        # Start the server process with the port as an argument
        process_args = [*server.args, "--port", str(actual_port)]
        process = await anyio.open_process(
            [server.command, *process_args],
            env=server.env or os.environ,
            stderr=errlog,
            cwd=server.cwd,
        )

        try:
            # Accept connection from the server with timeout
            stream = None
            connection_event = anyio.Event()

            async def handle_connection(client_stream):
                nonlocal stream
                stream = client_stream
                logger.info(f"Accepted connection from server")
                connection_event.set()

            async def run_listener():
                try:
                    async with listener:
                        await listener.serve(handle_connection)
                except anyio.get_cancelled_exc_class():
                    # Normal cancellation, just exit
                    pass
                except Exception as e:
                    logger.error(f"Error in listener: {e}")
                    raise

            async def socket_reader():
                """Reads messages from the socket and forwards them to read_stream."""
                try:
                    async with read_stream_writer:
                        buffer = ""
                        async for data in stream:
                            text = data.decode(
                                server.encoding, server.encoding_error_handler
                            )
                            lines = (buffer + text).split("\n")
                            buffer = lines.pop()

                            for line in lines:
                                try:
                                    message = types.JSONRPCMessage.model_validate_json(
                                        line
                                    )
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

            async def socket_writer():
                """Reads messages from write_stream and sends them over the socket."""
                try:
                    async with write_stream_reader:
                        async for session_message in write_stream_reader:
                            json = session_message.message.model_dump_json(
                                by_alias=True, exclude_none=True
                            )
                            data = (json + "\n").encode(
                                server.encoding, server.encoding_error_handler
                            )
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

            async with anyio.create_task_group() as tg:
                # Start the listener task
                tg.start_soon(run_listener)

                # Wait for connection with timeout
                with anyio.fail_after(server.connection_timeout):
                    await connection_event.wait()

                # Start reader and writer tasks
                tg.start_soon(socket_reader)
                tg.start_soon(socket_writer)

                try:
                    async with process, stream:
                        yield read_stream, write_stream
                finally:
                    # Cancel all tasks and clean up with timeout
                    tg.cancel_scope.cancel()

                    # Force cleanup with timeout to prevent hanging
                    try:
                        with anyio.fail_after(5.0):  # 5 second timeout for cleanup
                            # Clean up process to prevent any dangling orphaned processes
                            try:
                                process.terminate()
                            except ProcessLookupError:
                                # Process already exited, which is fine
                                pass
                            await read_stream.aclose()
                            await write_stream.aclose()
                            await read_stream_writer.aclose()
                            await write_stream_reader.aclose()
                    except anyio.get_cancelled_exc_class():
                        # If cleanup times out, force kill the process
                        logger.warning("Cleanup timed out, force killing process")
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass

        finally:
            # Clean up process
            if process.returncode is None:
                process.terminate()
            await process.aclose()

    finally:
        # Clean up listener
        await listener.aclose()
