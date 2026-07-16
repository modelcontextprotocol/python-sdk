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
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from io import TextIOWrapper
from typing import BinaryIO, Literal, TextIO

import anyio
import anyio.lowlevel
import mcp_types as types

from mcp.os.posix.utilities import same_open_file
from mcp.os.win32.utilities import rebind_std_handle_to_fd
from mcp.shared._context_streams import create_context_streams
from mcp.shared.message import SessionMessage

# Descriptors a transport in this process currently has pointed away from
# their protocol pipes. A second concurrent stdio_server() must not claim an
# fd again: it would duplicate the diversion target instead of the protocol
# pipe, and its restore would clobber the first transport's. The lock makes
# the check-and-claim atomic for embedders running transports on threads.
_claimed: set[int] = set()
_claimed_lock = threading.Lock()


def _is_backed_by_fd(stream: TextIO, fd: int) -> bool:
    """Whether stream is a text wrapper over the process's real descriptor fd."""
    try:
        return stream.buffer.fileno() == fd
    except (AttributeError, OSError, ValueError):
        # In-memory or injected streams (tests, embedders) have no usable
        # descriptor; io.UnsupportedOperation is a subclass of OSError/ValueError.
        return False


def _dup_above_std(fd: int) -> int:
    """Duplicates fd onto a descriptor above the standard range (fd > 2).

    os.dup hands out the lowest free slot, so in a process started with a
    standard descriptor closed the private wire duplicate would itself become
    fd 0, 1, or 2 - handed to children as a standard stream, and, when it
    lands on fd 2, silently made the target of the stdout diversion.

    Raises:
        OSError: propagated from os.dup; nothing is leaked into the standard
            range - every duplicate made so far is closed first.
    """
    duplicates = [os.dup(fd)]
    try:
        while duplicates[-1] <= 2:
            duplicates.append(os.dup(fd))
    except OSError:
        for duplicate in duplicates:
            os.close(duplicate)
        raise
    for below_std in duplicates[:-1]:
        os.close(below_std)
    return duplicates[-1]


def _open_stdin_diversion() -> int:
    """What fd 0 reads while claimed: the null device, so readers see EOF."""
    return os.open(os.devnull, os.O_RDONLY)


def _open_stdout_diversion() -> int:
    """What fd 1 receives while claimed: stderr, where stray output is at least
    visible in the client's logs, or the null device when stderr is unusable
    or is itself the wire (stderr merged into stdout, the 2>&1 launch shape -
    detectable on POSIX; on Windows such a merge keeps its v1 behavior)."""
    if not same_open_file(2, 1):
        try:
            return os.dup(2)
        except OSError:
            pass
    return os.open(os.devnull, os.O_WRONLY)


def _claim_fd(
    fd: int, stream: TextIO, mode: Literal["rb", "wb"], open_diversion: Callable[[], int]
) -> tuple[BinaryIO, Callable[[], None] | None]:
    """Returns the binary stream the transport uses for the protocol, and its undo.

    When stream is the process's real standard stream, moves the protocol pipe
    to a private descriptor and points fd (and, on Windows, the matching
    standard handle) at the diversion for the transport's lifetime, so handler
    code and its child processes touch the diversion instead of the protocol
    pipe; stdio_server's docstring describes the resulting behavior.

    The claim is best-effort: when the descriptors cannot be rearranged the
    transport serves the sys stream's buffer in place, exactly as before
    isolation existed, and when a transport in this process already claimed
    fd it serves a fresh buffered view of wherever fd currently points. In
    both cases the undo callback is None. A stream with no real descriptor
    is served through its own buffer.
    """
    if not _is_backed_by_fd(stream, fd):
        return stream.buffer, None
    # Claimed before touching the descriptor table so a second transport
    # entering mid-claim serves in place instead of duplicating a half-moved
    # descriptor.
    with _claimed_lock:
        already_claimed = fd in _claimed
        if not already_claimed:
            _claimed.add(fd)
    if already_claimed:
        # An enclosing transport owns the claim. Serve wherever fd currently
        # points - the diversion - through a fresh view rather than the sys
        # stream's buffer: its cached seekability describes the pre-claim
        # target, and interrogating it can fail on the retargeted descriptor.
        return open(fd, mode, closefd=False), None
    private_fd = None
    try:
        private_fd = _dup_above_std(fd)
        diversion_fd = open_diversion()
        try:
            os.dup2(diversion_fd, fd)
        finally:
            os.close(diversion_fd)
        if sys.platform == "win32":  # pragma: no cover
            rebind_std_handle_to_fd(fd)
    except OSError:
        with _claimed_lock:
            _claimed.discard(fd)
        if private_fd is not None:
            # A completed dup2 is undone; an untouched fd is re-pointed at
            # the same pipe it already holds, which is harmless.
            _restore_fd(fd, private_fd)
            os.close(private_fd)
        # fd still holds the protocol pipe, so the sys stream's buffer is
        # target-consistent: serve it in place, exactly as v1 did - shared
        # write ordering, no new descriptors to allocate in a process whose
        # descriptor table is already failing.
        return stream.buffer, None

    def restore() -> None:
        # Flush first: text buffered in the sys stream during the claim (a
        # stray print() while stdout is claimed) drains to the diversion, not
        # to the restored protocol pipe.
        with suppress(OSError, ValueError):
            stream.flush()
        _restore_fd(fd, private_fd)
        with _claimed_lock:
            _claimed.discard(fd)

    # closefd=False: an I/O call may sit blocked on this descriptor in a
    # worker thread past the transport's lifetime, so garbage collection of
    # the wrapper must never close (and free for reuse) the fd under it. The
    # private descriptor is deliberately left open for the same reason - one
    # descriptor per stream per session, restore() only points fd back at it.
    return os.fdopen(private_fd, mode, closefd=False), restore


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

    While serving on the process's real stdin and stdout, the transport claims
    them: each protocol pipe moves to a private descriptor, fd 0 (with the
    Windows standard input handle) reads the null device, and fd 1 (with the
    standard output handle) is diverted to stderr — the null device if stderr
    is unusable. Handler code and the child processes it spawns can therefore
    neither consume protocol bytes nor corrupt the outgoing stream: reads see
    end-of-file, and stray writes (a `print()`, a child's inherited stdout)
    land on stderr. Both descriptors are restored when the context exits.
    Passing an explicit stream skips the claim for that side.
    """
    # Purposely not using context managers for these, as we don't want to close
    # standard process handles. Encoding of stdin/stdout as text streams on
    # python is platform-dependent (Windows is particularly problematic), so we
    # re-wrap the underlying binary stream to ensure UTF-8.
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
