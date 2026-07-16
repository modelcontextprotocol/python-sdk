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
from contextlib import asynccontextmanager, suppress
from io import TextIOWrapper
from typing import BinaryIO, TextIO

import anyio
import anyio.lowlevel
import mcp_types as types

from mcp.os.win32.utilities import rebind_std_handle_to_fd
from mcp.shared._context_streams import create_context_streams
from mcp.shared.message import SessionMessage

# True while a transport in this process has fd 0 pointed at the null device.
# A second concurrent stdio_server() must not claim again: it would duplicate
# the null device instead of the protocol pipe, and its restore would clobber
# the first transport's.
_stdin_claimed = False


def _is_backed_by_fd(stream: TextIO, fd: int) -> bool:
    """Whether stream is a text wrapper over the process's real descriptor fd."""
    try:
        return stream.buffer.fileno() == fd
    except (AttributeError, OSError, ValueError):
        # In-memory or injected streams (tests, embedders) have no usable
        # descriptor; io.UnsupportedOperation is a subclass of OSError/ValueError.
        return False


def _claim_stdin() -> tuple[BinaryIO, Callable[[], None] | None]:
    """Returns the binary stream the transport reads the protocol from, and its undo.

    When running on the process's real stdin, moves the protocol pipe to a
    private descriptor and points fd 0 (and, on Windows, the standard input
    handle) at the null device for the transport's lifetime. Child processes
    spawned by handlers then inherit the null device instead of the protocol
    pipe: a child holding the protocol pipe could consume protocol bytes, and
    on Windows a Python child hangs during interpreter startup while the
    transport's blocking read is pending on the shared pipe
    (https://github.com/python/cpython/issues/78961).

    Isolation is best-effort: when the descriptors cannot be rearranged, or a
    transport in this process already claimed stdin, the returned stream is
    sys.stdin.buffer read in place (the pre-isolation behavior) and the undo
    callback is None.
    """
    global _stdin_claimed
    if _stdin_claimed or not _is_backed_by_fd(sys.stdin, 0):
        return sys.stdin.buffer, None
    # Set before touching the descriptor table so a second transport entering
    # mid-claim serves in place instead of duplicating a half-moved fd 0.
    _stdin_claimed = True
    private_fd = None
    try:
        private_fd = os.dup(0)
        devnull_fd = os.open(os.devnull, os.O_RDONLY)
        try:
            os.dup2(devnull_fd, 0)
        finally:
            os.close(devnull_fd)
        if sys.platform == "win32":  # pragma: no cover
            rebind_std_handle_to_fd(0)
    except OSError:
        _stdin_claimed = False
        # Isolation is best-effort: serve stdin in place, as before it existed.
        if private_fd is not None:
            # A completed dup2 is undone; an untouched fd 0 is re-pointed at
            # the same pipe it already holds, which is harmless.
            _restore_fd(0, private_fd)
            os.close(private_fd)
        return sys.stdin.buffer, None

    def restore() -> None:
        global _stdin_claimed
        _restore_fd(0, private_fd)
        _stdin_claimed = False

    # closefd=False: the reader may sit in a blocking read on this descriptor
    # in a worker thread past the transport's lifetime, so garbage collection
    # of the wrapper must never close (and free for reuse) the fd under it.
    return os.fdopen(private_fd, "rb", closefd=False), restore


def _restore_fd(fd: int, private_fd: int) -> None:
    """Points fd back at the protocol stream the transport claimed.

    Best-effort: a failure must never mask whatever ended the transport, so it
    is swallowed rather than raised out of stdio_server's finally.
    """
    with suppress(OSError):
        os.dup2(private_fd, fd)
        if sys.platform == "win32":  # pragma: no cover
            rebind_std_handle_to_fd(fd)


@asynccontextmanager
async def stdio_server(stdin: anyio.AsyncFile[str] | None = None, stdout: anyio.AsyncFile[str] | None = None):
    """Server transport for stdio: this communicates with an MCP client by reading
    from the current process' stdin and writing to stdout.

    While serving on the process's real stdin, the transport claims it: the
    protocol pipe moves to a private descriptor and fd 0 (with the Windows
    standard input handle) reads the null device, so handler code and its
    child processes cannot touch the protocol stream. Both are restored when
    the context exits. Passing an explicit stdin skips this entirely.
    """
    # Purposely not using context managers for these, as we don't want to close
    # standard process handles. Encoding of stdin/stdout as text streams on
    # python is platform-dependent (Windows is particularly problematic), so we
    # re-wrap the underlying binary stream to ensure UTF-8.
    restore_stdin: Callable[[], None] | None = None
    try:
        if not stdin:
            stdin_buffer, restore_stdin = _claim_stdin()
            stdin = anyio.wrap_file(TextIOWrapper(stdin_buffer, encoding="utf-8", errors="replace"))
        if not stdout:
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

        async with anyio.create_task_group() as tg:
            tg.start_soon(stdin_reader)
            tg.start_soon(stdout_writer)
            yield read_stream, write_stream
    finally:
        if restore_stdin is not None:
            restore_stdin()
