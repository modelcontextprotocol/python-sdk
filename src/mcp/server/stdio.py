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
import queue
import sys
import threading
from collections.abc import Callable
from concurrent.futures import CancelledError
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from io import TextIOWrapper
from typing import BinaryIO, Literal, TextIO

import anyio
import anyio.lowlevel
import mcp_types as types
from anyio.from_thread import BlockingPortal

from mcp.os.win32.utilities import rebind_std_handle_to_fd
from mcp.shared._context_streams import create_context_streams
from mcp.shared.message import SessionMessage

if sys.platform != "win32":  # pragma: no branch
    import fcntl  # pragma: lax no cover - POSIX-only line, uncovered on Windows runners

# Stream-claim contract (design and attack log in PR #3117):
# - _claims is the single authority for who owns fd 0/1; mutated only under the
#   lock, only by acquire's insert and release's deregister.
# - private_fd is recorded the instant the wire duplicate exists, before fd is
#   ever moved, and is never closed while the claim is registered.
# - Release deregisters only after dup2(private_fd, fd) restores the wire; a
#   failed release keeps the claim, so successors are refused, never fed a
#   diverted descriptor. Every failure lands on that safe side.
_claims: dict[int, "_StreamClaim"] = {}
_claims_lock = threading.Lock()
_STDOUT_DRAIN_TIMEOUT_SECONDS = 1.0


@dataclass
class _StreamClaim:
    fd: int
    private_fd: int | None = None
    pending_io: threading.Event | None = None
    released: bool = False


class _UnownedTextWrapper(TextIOWrapper):
    """Text layer whose close never closes the underlying buffer.

    The buffer is not the transport's to close: in the in-place paths it is the
    sys stream's own buffer, and closing it at garbage collection destroyed
    sys.stdout for the rest of the process (issue #1933).
    """

    def close(self) -> None:
        with suppress(ValueError):
            self.detach()


def _is_backed_by_fd(stream: TextIO, fd: int) -> bool:
    try:
        return stream.buffer.fileno() == fd
    except (AttributeError, OSError, ValueError):
        return False


def _dup_above_std(fd: int) -> int:
    """Duplicate fd onto a descriptor that cannot land in the standard range."""
    if sys.platform == "win32":  # pragma: no cover
        duplicate = os.dup(fd)
        if duplicate <= 2:
            os.close(duplicate)
            raise OSError(f"duplicate of fd {fd} landed in the standard range")
        return duplicate
    return fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 3)  # pragma: lax no cover - POSIX-only


def _open_stdin_diversion() -> int:
    return os.open(os.devnull, os.O_RDONLY)


def _open_stdout_diversion() -> int:
    try:
        return os.dup(2)
    except OSError:
        return os.open(os.devnull, os.O_WRONLY)


def _restore_fd(fd: int, private_fd: int) -> bool:
    """Point fd back at the wire; the Windows handle rebind never affects the outcome."""
    try:
        os.dup2(private_fd, fd)
    except OSError:
        return False
    if sys.platform == "win32":  # pragma: no cover
        with suppress(OSError):
            rebind_std_handle_to_fd(fd)
    return True


def _claim_fd(
    fd: int,
    stream: TextIO,
    mode: Literal["rb", "wb"],
    open_diversion: Callable[[], int],
    pending_io: threading.Event | None = None,
) -> tuple[BinaryIO, Callable[[], None] | None]:
    """Claim a standard stream: divert fd and serve the wire from a private duplicate.

    Best-effort: when descriptors cannot be duplicated or diverted, serves the
    sys stream's buffer in place, exactly as v1 did, with the claim held.

    Raises:
        RuntimeError: fd is already claimed by another transport in this process.
    """
    if not _is_backed_by_fd(stream, fd):
        return stream.buffer, None
    claim = _StreamClaim(fd, pending_io=pending_io)
    with _claims_lock:
        previous = _claims.get(fd)
        if (
            previous is not None
            and previous.released
            and previous.pending_io is not None
            and previous.pending_io.is_set()
        ):
            del _claims[fd]
        if fd in _claims:
            raise RuntimeError(f"another stdio_server() in this process has already claimed fd {fd}")
        _claims[fd] = claim

    def release() -> None:
        if claim.private_fd is None or _restore_fd(fd, claim.private_fd):
            with _claims_lock:
                claim.released = True
                # A timed-out writer still owns the wire. Refuse a successor
                # until it finishes, even though fd 1 has been restored.
                if claim.pending_io is None or claim.pending_io.is_set():
                    del _claims[fd]

    try:
        private_fd = _dup_above_std(fd)
    except OSError:
        return stream.buffer, release
    claim.private_fd = private_fd

    try:
        diversion_fd = open_diversion()
    except OSError:
        return stream.buffer, release
    try:
        os.dup2(diversion_fd, fd)
    except OSError:
        # The divert did not land; ensure fd carries the wire (a Windows dup2 can
        # close its target before failing), then serve it in place through the
        # shared buffer, since two writers on one pipe would tear frames.
        with suppress(OSError):
            os.close(diversion_fd)
        _restore_fd(fd, private_fd)
        return stream.buffer, release
    with suppress(OSError):
        os.close(diversion_fd)
    if sys.platform == "win32":  # pragma: no cover
        with suppress(OSError):
            rebind_std_handle_to_fd(fd)

    # closefd=False: a worker thread can still block on this descriptor after
    # the transport exits, so it must never be closed and recycled under it.
    return os.fdopen(private_fd, mode, closefd=False), release


class _StdoutWriter:
    """One daemon thread, with at most one response awaiting completion."""

    def __init__(
        self,
        write: Callable[[str], None],
        close: Callable[[], None],
        portal: BlockingPortal,
        stopped: threading.Event,
    ) -> None:
        self._write = write
        self._close = close
        self._portal = portal
        self._stopped = stopped
        self._finished = anyio.Event()
        self._stopping = threading.Event()
        self._queue: queue.SimpleQueue[tuple[str, anyio.Event] | None] = queue.SimpleQueue()
        self._error: Exception | None = None
        self._thread = threading.Thread(target=self._run, name="mcp-stdout", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            while (item := self._queue.get()) is not None:
                text, complete = item
                try:
                    self._write(text)
                except Exception as exc:
                    # Thread boundary: report the original write/flush failure
                    # from the async writer, rather than losing it in the thread.
                    self._error = exc
                if not self._stopping.is_set():
                    # A write can complete after the drain deadline and portal exit.
                    with suppress(RuntimeError, CancelledError):
                        self._portal.call(complete.set)
                if self._error is not None:
                    return
        finally:
            self._close()
            self._stopped.set()
            with suppress(RuntimeError, CancelledError):
                self._portal.call(self._finished.set)

    async def write(self, text: str) -> None:
        complete = anyio.Event()
        self._queue.put((text, complete))
        await complete.wait()
        if self._error is not None:
            raise self._error

    def stop(self) -> None:
        self._stopping.set()
        self._queue.put(None)

    async def wait_stopped(self) -> None:
        await self._finished.wait()


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
    writer_stopped = threading.Event()
    writer: _StdoutWriter | None = None
    stdout_fd: int | None = None
    process_stdout = stdout is None or stdout.wrapped is sys.stdout
    output_encoding = "utf-8"
    output_errors = "strict"
    if stdout is not None and stdout.wrapped is sys.stdout:
        output_encoding = sys.stdout.encoding or "utf-8"
        output_errors = sys.stdout.errors or "strict"
    try:
        if not stdin:
            stdin_buffer, restore_stdin = _claim_fd(0, sys.stdin, "rb", _open_stdin_diversion)
            stdin = anyio.wrap_file(_UnownedTextWrapper(stdin_buffer, encoding="utf-8", errors="replace"))
        if not stdout:
            stdout_buffer, restore_stdout = _claim_fd(1, sys.stdout, "wb", _open_stdout_diversion, writer_stopped)
            stdout = anyio.wrap_file(_UnownedTextWrapper(stdout_buffer, encoding="utf-8"))
        if process_stdout:
            try:
                output_fileno = stdout.wrapped.fileno()
            except (AttributeError, OSError, ValueError):
                pass
            else:
                # Windows CRT writes lock their fd. Keep restoration's source
                # descriptor separate so dup2 cannot wait on a blocked write.
                stdout_fd = os.dup(output_fileno)

        def write_stdout(text: str) -> None:
            if stdout_fd is None:
                stdout.wrapped.write(text)
                stdout.wrapped.flush()
            else:
                # Bypass buffered locks, including sys.stdout.buffer in the
                # degraded path: Python flushes that buffer during finalization.
                data = memoryview(text.replace("\n", os.linesep).encode(output_encoding, errors=output_errors))
                while data:
                    written = os.write(stdout_fd, data)
                    data = data[written:]

        def close_stdout() -> None:
            if stdout_fd is not None:
                os.close(stdout_fd)

        read_stream_writer, read_stream = create_context_streams[SessionMessage | Exception](0)
        write_stream, write_stream_reader = create_context_streams[SessionMessage](0)
        stdout_done = anyio.Event()

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
                        assert writer is not None
                        await writer.write(json + "\n")
            except anyio.ClosedResourceError:
                await anyio.lowlevel.checkpoint()
            finally:
                stdout_done.set()

        async with BlockingPortal() as portal:
            writer = _StdoutWriter(write_stdout, close_stdout, portal, writer_stopped)
            writer.start()
            drain_deadline = float("inf")
            try:
                async with anyio.create_task_group() as tg:
                    tg.start_soon(stdin_reader)
                    tg.start_soon(stdout_writer)
                    try:
                        yield read_stream, write_stream
                    finally:
                        await write_stream.aclose()
                        # This is a separate transport budget, after the caller's
                        # handler drain. Cancelling an AnyIO file worker cannot
                        # interrupt write(2) or let its non-daemon thread exit.
                        drain_deadline = anyio.current_time() + _STDOUT_DRAIN_TIMEOUT_SECONDS
                        with anyio.CancelScope(deadline=drain_deadline, shield=True):
                            await stdout_done.wait()
                        tg.cancel_scope.cancel()
            finally:
                writer.stop()
                with anyio.CancelScope(deadline=drain_deadline, shield=True):
                    await writer.wait_stopped()
    finally:
        if writer is None:
            writer_stopped.set()
        if restore_stdout is not None:
            restore_stdout()
        if restore_stdin is not None:
            restore_stdin()
