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

import os
import sys
from collections.abc import Callable
from contextlib import asynccontextmanager
from io import TextIOWrapper, UnsupportedOperation
from typing import BinaryIO, Literal, Protocol

import anyio
import anyio.lowlevel

from mcp import types
from mcp.shared._context_streams import create_context_streams
from mcp.shared.message import SessionMessage


class _TextStreamWithBuffer(Protocol):
    @property
    def buffer(self) -> BinaryIO: ...

    fileno: Callable[[], int]


def _wrap_standard_stream(
    stream: _TextStreamWithBuffer,
    mode: Literal["rb", "wb"],
    *,
    errors: str | None = None,
) -> tuple[anyio.AsyncFile[str], bool]:
    """Wrap a standard stream without taking ownership of the original handle."""
    try:
        fd = os.dup(stream.fileno())
    except (AttributeError, OSError, UnsupportedOperation):
        return anyio.wrap_file(TextIOWrapper(stream.buffer, encoding="utf-8", errors=errors)), False

    binary = os.fdopen(fd, mode, closefd=True)
    return anyio.wrap_file(TextIOWrapper(binary, encoding="utf-8", errors=errors)), True


@asynccontextmanager
async def stdio_server(stdin: anyio.AsyncFile[str] | None = None, stdout: anyio.AsyncFile[str] | None = None):
    """Server transport for stdio: this communicates with an MCP client by reading
    from the current process' stdin and writing to stdout.
    """
    # Purposely not using context managers for these, as we don't want to close
    # standard process handles. Encoding of stdin/stdout as text streams on
    # python is platform-dependent (Windows is particularly problematic), so we
    # re-wrap duplicate file descriptors to ensure UTF-8 without taking
    # ownership of the original standard streams.
    close_stdin = False
    close_stdout = False
    if not stdin:
        stdin, close_stdin = _wrap_standard_stream(sys.stdin, "rb", errors="replace")
    if not stdout:
        stdout, close_stdout = _wrap_standard_stream(sys.stdout, "wb")

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
        if close_stdin:
            await stdin.aclose()
        if close_stdout:
            await stdout.aclose()
