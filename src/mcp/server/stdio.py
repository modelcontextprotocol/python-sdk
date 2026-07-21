"""Stdio server transport for MCP.

Example:
    ```python
    async def run_server():
        async with stdio_server() as (read_stream, write_stream):
            server = await create_my_server()
            await server.run(read_stream, write_stream, init_options)

    anyio.run(run_server)
    ```
"""

import os
import sys
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from io import TextIOWrapper
from typing import BinaryIO, Literal, TextIO

import anyio
import anyio.lowlevel
import mcp_types as types

from mcp.os.win32.utilities import rebind_std_handle_to_fd
from mcp.shared._context_streams import create_context_streams
from mcp.shared.message import SessionMessage

# fds whose real stream a serving transport owns, whether diverted or served in place.
_claimed: set[int] = set()
_claimed_lock = threading.Lock()


def _is_backed_by_fd(stream: TextIO, fd: int) -> bool:
    try:
        return stream.buffer.fileno() == fd
    except (AttributeError, OSError, ValueError):
        return False


def _std_descriptors_open() -> bool:
    """Whether fds 0-2 are all open, so a dup cannot land in the standard range."""
    try:
        for fd in (0, 1, 2):
            os.fstat(fd)
    except OSError:
        return False
    return True


def _open_stdin_diversion() -> int:
    return os.open(os.devnull, os.O_RDONLY)


def _open_stdout_diversion() -> int:
    try:
        return os.dup(2)
    except OSError:
        return os.open(os.devnull, os.O_WRONLY)


def _claim_fd(
    fd: int, stream: TextIO, mode: Literal["rb", "wb"], open_diversion: Callable[[], int]
) -> tuple[BinaryIO, Callable[[], None] | None]:
    """Move the protocol pipe to a private descriptor and divert fd while serving.

    Raises:
        RuntimeError: fd is already claimed by another transport in this process.
    """
    if not _is_backed_by_fd(stream, fd):
        return stream.buffer, None
    with _claimed_lock:
        if fd in _claimed:
            raise RuntimeError(f"another stdio_server() in this process has already claimed fd {fd}")
        _claimed.add(fd)

    def unclaim() -> None:
        with _claimed_lock:
            _claimed.discard(fd)

    if not _std_descriptors_open():
        return stream.buffer, unclaim
    private_fd = None
    try:
        private_fd = os.dup(fd)
        diversion_fd = open_diversion()
        try:
            os.dup2(diversion_fd, fd)
        finally:
            os.close(diversion_fd)
        if sys.platform == "win32":  # pragma: no cover
            rebind_std_handle_to_fd(fd)
    except OSError:
        if private_fd is not None:
            _restore_fd(fd, private_fd)
            os.close(private_fd)
        return stream.buffer, unclaim

    def restore() -> None:
        # Drain text buffered during the claim (a stray print) to the diversion.
        with suppress(OSError, ValueError):
            stream.flush()
        # A failed restore leaves fd diverted; keep it claimed so later transports are refused.
        if _restore_fd(fd, private_fd):
            unclaim()

    # closefd=False: a blocked worker thread may still read this descriptor after exit.
    return os.fdopen(private_fd, mode, closefd=False), restore


def _restore_fd(fd: int, private_fd: int) -> bool:
    """Point fd back at the protocol pipe; a failure never masks the transport's exit."""
    try:
        os.dup2(private_fd, fd)
        if sys.platform == "win32":  # pragma: no cover
            rebind_std_handle_to_fd(fd)
    except OSError:
        return False
    return True


@asynccontextmanager
async def stdio_server(stdin: anyio.AsyncFile[str] | None = None, stdout: anyio.AsyncFile[str] | None = None):
    """Serve MCP over the process's stdin and stdout.

    While serving, fd 0 points at the null device and fd 1 at stderr, so handlers
    and children read EOF and their stray output misses the wire; both descriptors
    are restored on exit. Explicit streams skip the claim, and a second concurrent
    stdio_server() raises RuntimeError.
    """
    # Re-wrap the binary buffers as UTF-8 text; the std handles' platform encodings are unreliable.
    restore_stdin: Callable[[], None] | None = None
    restore_stdout: Callable[[], None] | None = None
    try:
        if not stdin:
            stdin_buffer, restore_stdin = _claim_fd(0, sys.stdin, "rb", _open_stdin_diversion)
            stdin = anyio.wrap_file(TextIOWrapper(stdin_buffer, encoding="utf-8", errors="replace"))
        if not stdout:
            stdout_buffer, restore_stdout = _claim_fd(1, sys.stdout, "wb", _open_stdout_diversion)
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

        async with anyio.create_task_group() as tg:
            tg.start_soon(stdin_reader)
            tg.start_soon(stdout_writer)
            yield read_stream, write_stream
    finally:
        if restore_stdout is not None:
            restore_stdout()
        if restore_stdin is not None:
            restore_stdin()
