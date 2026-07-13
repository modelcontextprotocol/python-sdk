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
from typing import TextIO

import anyio
import anyio.lowlevel
import mcp_types as types

from mcp.shared._context_streams import create_context_streams
from mcp.shared.message import SessionMessage


@asynccontextmanager
async def stdio_server(stdin: anyio.AsyncFile[str] | None = None, stdout: anyio.AsyncFile[str] | None = None):
    """Server transport for stdio: this communicates with an MCP client by reading
    from the current process' stdin and writing to stdout.
    """
    # We don't want to close the process' standard handles. Wrapping
    # sys.std{in,out}.buffer in a TextIOWrapper is not enough on its own: the
    # wrapper's __del__ finalizer closes the buffer it wraps, so once the wrapper
    # is garbage-collected the real sys.std{in,out} is closed and any later
    # print()/read raises "ValueError: I/O operation on closed file." (#1933).
    # Encoding of stdin/stdout as text streams on python is platform-dependent
    # (Windows is particularly problematic), so we still re-wrap the underlying
    # binary stream to ensure UTF-8.
    #
    # Preferred path: dup the underlying fd (os.dup is Windows-safe) and wrap the
    # copy, so the wrapper only ever closes the duplicate; we close those wrappers
    # on exit to free the dup'd fds. When sys.std* has no real fd (pytest capture,
    # embedded interpreters, injected in-memory streams), we fall back to wrapping
    # .buffer directly and detach() the wrapper on exit, which severs it from the
    # buffer without closing it -- so the finalizer can no longer close the real
    # handle either.
    to_close: list[TextIOWrapper] = []
    to_detach: list[TextIOWrapper] = []

    def wrap_std(std: TextIO, mode: str, errors: str | None) -> anyio.AsyncFile[str]:
        try:
            binary = open(os.dup(std.fileno()), mode + "b", closefd=True)
            wrapper = TextIOWrapper(binary, encoding="utf-8", errors=errors)
            to_close.append(wrapper)
        except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
            # No real fd. A bufferless in-memory text stream (e.g. io.StringIO)
            # has no .buffer to re-wrap, so use it directly -- it is already text,
            # and we did not create it, so there is nothing to tear down. Otherwise
            # re-wrap .buffer and detach() on exit so the finalizer cannot close the
            # real handle.
            if not hasattr(std, "buffer"):
                return anyio.wrap_file(std)
            wrapper = TextIOWrapper(std.buffer, encoding="utf-8", errors=errors)
            to_detach.append(wrapper)
        return anyio.wrap_file(wrapper)

    if not stdin:
        stdin = wrap_std(sys.stdin, "r", errors="replace")
    if not stdout:
        stdout = wrap_std(sys.stdout, "w", errors=None)

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
        # Close the wrappers around dup'd fds (frees the duplicate) and detach the
        # wrappers around the real .buffer (severs them without closing the real
        # handle, so their finalizers can't close it either). Neither touches the
        # process' standard handles or a caller-injected stream.
        for wrapper in to_close:
            wrapper.close()
        for wrapper in to_detach:
            wrapper.detach()
