"""Stdio Server Transport Module

This module provides functionality for creating an stdio-based transport layer
that can be used to communicate with an MCP client through standard input/output
streams.

Example:
    ```python
    async def run_server():
        async with stdio_server() as (read_stream, write_stream):
            # read_stream contains incoming JSONRPCMessages from stdin
            # write_stream allows sending JSONRPCMessages to stdout
            server = await create_my_server()
            await server.run(read_stream, write_stream, init_options)

    anyio.run(run_server)
    ```
"""

import io
import os
import sys
from contextlib import asynccontextmanager
from io import TextIOWrapper

import anyio
import anyio.lowlevel
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp import types
from mcp.shared.message import SessionMessage


@asynccontextmanager
async def stdio_server(stdin: anyio.AsyncFile[str] | None = None, stdout: anyio.AsyncFile[str] | None = None):
    """Server transport for stdio: this communicates with an MCP client by reading
    from the current process' stdin and writing to stdout.
    """
    # We duplicate file descriptors when using the real stdin/stdout to avoid
    # closing the process's standard handles when the TextIOWrapper is closed.
    # This allows the process to continue using stdio normally after the server exits.
    # For streams without a fileno() (e.g., in-memory streams in tests), we fall back
    # to wrapping them directly.
    if not stdin:
        try:
            stdin_fd = os.dup(sys.stdin.fileno())
            stdin_bin = os.fdopen(stdin_fd, "rb", closefd=True)
            stdin = anyio.wrap_file(TextIOWrapper(stdin_bin, encoding="utf-8", errors="replace"))
        except (OSError, io.UnsupportedOperation):
            # Fallback for streams that don't support fileno() (e.g., BytesIO in tests)
            stdin = anyio.wrap_file(TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace"))
    if not stdout:
        try:
            stdout_fd = os.dup(sys.stdout.fileno())
            stdout_bin = os.fdopen(stdout_fd, "wb", closefd=True)
            stdout = anyio.wrap_file(TextIOWrapper(stdout_bin, encoding="utf-8"))
        except (OSError, io.UnsupportedOperation):
            # Fallback for streams that don't support fileno() (e.g., BytesIO in tests)
            stdout = anyio.wrap_file(TextIOWrapper(sys.stdout.buffer, encoding="utf-8"))

    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]

    write_stream: MemoryObjectSendStream[SessionMessage]
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    async def stdin_reader():
        try:
            async with read_stream_writer:
                async for line in stdin:
                    try:
                        message = types.jsonrpc_message_adapter.validate_json(line, by_name=False)
                    except Exception as exc:
                        await read_stream_writer.send(exc)
                        continue

                    session_message = SessionMessage(message)
                    await read_stream_writer.send(session_message)
        except anyio.ClosedResourceError:  # pragma: no cover
            await anyio.lowlevel.checkpoint()

    async def stdout_writer():
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    json = session_message.message.model_dump_json(by_alias=True, exclude_unset=True)
                    await stdout.write(json + "\n")
                    await stdout.flush()
        except anyio.ClosedResourceError:  # pragma: no cover
            await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdin_reader)
        tg.start_soon(stdout_writer)
        yield read_stream, write_stream
