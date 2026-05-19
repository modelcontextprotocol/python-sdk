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

from mcp import types
from mcp.shared._context_streams import create_context_streams
from mcp.shared.message import SessionMessage


@asynccontextmanager
async def stdio_server(stdin: anyio.AsyncFile[str] | None = None, stdout: anyio.AsyncFile[str] | None = None):
    """Server transport for stdio: this communicates with an MCP client by reading
    from the current process' stdin and writing to stdout.
    """
    # Re-wrap the underlying binary stream to ensure UTF-8 (encoding is
    # platform-dependent on Windows). Use os.dup() to duplicate the file
    # descriptor so that closing our wrapper does not close the real process
    # stdin/stdout (issue #1933). Falls back to sharing the original buffer
    # when the stream is not backed by a real file descriptor (e.g. BytesIO
    # in tests); in that case we must not close the wrapper on exit.
    stdin_created = False
    stdout_created = False

    if not stdin:
        stdin_buffer = sys.stdin.buffer
        try:
            stdin_buffer = os.fdopen(os.dup(stdin_buffer.fileno()), "rb")
            stdin_created = True
        except io.UnsupportedOperation:
            pass
        stdin = anyio.wrap_file(TextIOWrapper(stdin_buffer, encoding="utf-8", errors="replace"))
    if not stdout:
        stdout_buffer = sys.stdout.buffer
        try:
            stdout_buffer = os.fdopen(os.dup(stdout_buffer.fileno()), "wb")
            stdout_created = True
        except io.UnsupportedOperation:
            pass
        stdout = anyio.wrap_file(TextIOWrapper(stdout_buffer, encoding="utf-8"))

    read_stream_writer, read_stream = create_context_streams[SessionMessage | Exception](0)
    write_stream, write_stream_reader = create_context_streams[SessionMessage](0)

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

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(stdin_reader)
            tg.start_soon(stdout_writer)
            yield read_stream, write_stream
    finally:
        # Close the dup'd wrappers we own; do NOT close sys.stdin/sys.stdout.
        if stdin_created:
            await stdin.aclose()
        if stdout_created:
            await stdout.aclose()
