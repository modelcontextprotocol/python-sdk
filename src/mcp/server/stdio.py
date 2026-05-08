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
    # When stdin/stdout are not provided, duplicate the underlying file descriptors
    # so that closing the wrappers does not close the real sys.stdin/sys.stdout.
    # Encoding of stdin/stdout as text streams on Python is platform-dependent
    # (Windows is particularly problematic), so we re-wrap the underlying binary
    # stream to ensure UTF-8.
    _stdin_wrapper: TextIOWrapper | None = None
    _stdout_wrapper: TextIOWrapper | None = None

    if not stdin:
        try:
            stdin_fd = os.dup(sys.stdin.fileno())
            _stdin_wrapper = TextIOWrapper(os.fdopen(stdin_fd, "rb"), encoding="utf-8", errors="replace")
            stdin = anyio.wrap_file(_stdin_wrapper)
        except (AttributeError, io.UnsupportedOperation):
            # sys.stdin has no real fd (e.g. BytesIO in tests) — wrap buffer directly.
            # Closing this wrapper also closes the buffer, but that is harmless in
            # that context because there is no real fd to leak.
            stdin = anyio.wrap_file(TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace"))
    if not stdout:
        try:
            stdout_fd = os.dup(sys.stdout.fileno())
            _stdout_wrapper = TextIOWrapper(os.fdopen(stdout_fd, "wb"), encoding="utf-8")
            stdout = anyio.wrap_file(_stdout_wrapper)
        except (AttributeError, io.UnsupportedOperation):
            # sys.stdout has no real fd — wrap buffer directly (same reasoning as above).
            stdout = anyio.wrap_file(TextIOWrapper(sys.stdout.buffer, encoding="utf-8"))

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
        if _stdout_wrapper is not None:
            _stdout_wrapper.close()
        if _stdin_wrapper is not None:
            _stdin_wrapper.close()
