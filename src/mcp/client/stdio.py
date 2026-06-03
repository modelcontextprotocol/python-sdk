import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, TextIO

import anyio
import anyio.lowlevel
from anyio.abc import AsyncResource, Process
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from anyio.streams.text import TextReceiveStream
from pydantic import BaseModel, Field

from mcp import types
from mcp.os.posix.utilities import terminate_posix_process_tree
from mcp.os.win32.utilities import (
    FallbackProcess,
    close_process_job,
    create_windows_process,
    get_windows_executable_command,
    terminate_windows_process_tree,
)
from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)

# Environment variables to inherit by default
DEFAULT_INHERITED_ENV_VARS = (
    [
        "APPDATA",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "USERNAME",
        "USERPROFILE",
    ]
    if sys.platform == "win32"
    else ["HOME", "LOGNAME", "PATH", "SHELL", "TERM", "USER"]
)

# How long the server gets to exit on its own after its stdin is closed, before its
# process tree is terminated.
PROCESS_TERMINATION_TIMEOUT = 2.0

# How long the process tree gets to die after a graceful termination request
# (SIGTERM on POSIX) before it is force-killed. Windows tree termination is an
# immediate hard kill, so this only stretches the POSIX path.
FORCE_KILL_TIMEOUT = 2.0

# How long to wait for the event loop to observe the death of a killed process.
# Kill-death is prompt, so this normally takes one poll interval; the bound only
# matters for a process that even SIGKILL cannot collect (uninterruptible I/O).
_KILL_REAP_TIMEOUT = 2.0

# How long the writer task gets to hand already-accepted outbound messages to the
# server's stdin before shutdown closes it. Normally one scheduling round; only a
# wedged pipe (full, with its reader gone) makes it run out.
_WRITER_FLUSH_TIMEOUT = 0.5

# How often to poll for process death while waiting out the grace period.
_EXIT_POLL_INTERVAL = 0.01


def get_default_environment() -> dict[str, str]:
    """Returns a default environment object including only environment variables deemed
    safe to inherit.
    """
    env: dict[str, str] = {}

    for key in DEFAULT_INHERITED_ENV_VARS:
        value = os.environ.get(key)
        if value is None:  # pragma: lax no cover
            continue

        if value.startswith("()"):  # pragma: no cover
            # Skip functions, which are a security risk
            continue  # pragma: no cover

        env[key] = value

    return env


class StdioServerParameters(BaseModel):
    command: str
    """The executable to run to start the server."""

    args: list[str] = Field(default_factory=list)
    """Command line arguments to pass to the executable."""

    env: dict[str, str] | None = None
    """
    The environment to use when spawning the process.

    If not specified, the result of get_default_environment() will be used.
    """

    cwd: str | Path | None = None
    """The working directory to use when spawning the process."""

    encoding: str = "utf-8"
    """
    The text encoding used when sending/receiving messages to the server.

    Defaults to utf-8.
    """

    encoding_error_handler: Literal["strict", "ignore", "replace"] = "strict"
    """
    The text encoding error handler.

    See https://docs.python.org/3/library/codecs.html#codec-base-classes for
    explanations of possible values.
    """


@asynccontextmanager
async def stdio_client(server: StdioServerParameters, errlog: TextIO = sys.stderr):
    """Client transport for stdio: this will connect to a server by spawning a
    process and communicating with it over stdin/stdout.
    """
    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]

    write_stream: MemoryObjectSendStream[SessionMessage]
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    spawned = False
    try:
        command = _get_executable_command(server.command)

        # Open process with stderr piped for capture
        process = await _create_platform_compatible_process(
            command=command,
            args=server.args,
            env=({**get_default_environment(), **server.env} if server.env is not None else get_default_environment()),
            errlog=errlog,
            cwd=server.cwd,
        )
        spawned = True
    finally:
        if not spawned:
            # The spawn can fail with more than OSError: a cancellation delivered
            # while the interpreter cold-starts, or ValueError from a NUL byte in
            # the command. Close the streams on every failure or they leak to a
            # GC-time ResourceWarning. Shielded so a pending cancellation cannot
            # interrupt the closes.
            with anyio.CancelScope(shield=True):
                await _aclose_all(read_stream, write_stream, read_stream_writer, write_stream_reader)

    # Flipped by the shutdown sequence so the pipe tasks can tell expected
    # teardown noise from genuine mid-session transport failures.
    shutting_down = False
    # Set when stdin_writer finishes, so shutdown can wait (bounded) for messages
    # the transport already accepted to be flushed before it closes stdin.
    writer_done = anyio.Event()
    # Shutdown's final cancellation targets these instead of the task group's own
    # scope: cancelling the host scope would deliver the cancellation by throwing
    # through the caller's suspended frames, and Python 3.11's tracer loses
    # coverage events after such a throw() traversal (python/cpython#106749).
    # These scope exactly the work the pipe tasks own.
    reader_scope = anyio.CancelScope()
    writer_scope = anyio.CancelScope()

    async def stdout_reader() -> None:
        assert process.stdout, "Opened process is missing stdout"

        with reader_scope:
            # Once the read stream is gone, keep consuming stdout without delivering:
            # a server flushing its remaining output during shutdown must not block on
            # a full pipe and miss its chance to exit before the grace period ends.
            delivering = True
            try:
                async with read_stream_writer:
                    buffer = ""
                    async for chunk in TextReceiveStream(
                        process.stdout,
                        encoding=server.encoding,
                        errors=server.encoding_error_handler,
                    ):
                        if not delivering:
                            continue

                        lines = (buffer + chunk).split("\n")
                        buffer = lines.pop()

                        for line in lines:
                            item: SessionMessage | Exception
                            try:
                                message = types.jsonrpc_message_adapter.validate_json(line, by_name=False)
                            except ValueError as exc:
                                logger.exception("Failed to parse JSONRPC message from server")
                                item = exc
                            else:
                                item = SessionMessage(message)

                            try:
                                await read_stream_writer.send(item)
                            except (anyio.ClosedResourceError, anyio.BrokenResourceError):
                                # The read stream is gone — shutdown closed it, or the
                                # caller did. Stop delivering but keep draining.
                                delivering = False
                                break
            except anyio.ClosedResourceError:
                # Our own shutdown closed/poisoned the stdout stream under the read.
                await anyio.lowlevel.checkpoint()
            except (anyio.BrokenResourceError, ConnectionError):
                # The stdout pipe itself failed. During shutdown that's expected (the
                # process may be killed mid-read, which the proactor backend surfaces
                # as ConnectionResetError); mid-session it's a real transport failure
                # worth a log line. Either way the session observes a clean closure
                # when this task's exit closes the read stream.
                if not shutting_down:
                    logger.exception("Reading from the MCP server's stdout failed mid-session")
                await anyio.lowlevel.checkpoint()

    async def stdin_writer() -> None:
        assert process.stdin, "Opened process is missing stdin"

        with writer_scope:
            try:
                async with write_stream_reader:
                    async for session_message in write_stream_reader:
                        json = session_message.message.model_dump_json(by_alias=True, exclude_unset=True)
                        await process.stdin.send(
                            (json + "\n").encode(
                                encoding=server.encoding,
                                errors=server.encoding_error_handler,
                            )
                        )
            except (anyio.ClosedResourceError, anyio.BrokenResourceError, OSError):
                # The server stopped reading — its process died, it closed its stdin,
                # or shutdown closed the pipe under a racing write. The exact exception
                # depends on platform and backend; all of them just mean the pipe is
                # gone. The server may well still be alive, so close the read stream to
                # tell the session the connection is over — a silently swallowed write
                # would otherwise leave a request waiting forever for its response.
                await read_stream_writer.aclose()
            finally:
                writer_done.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdout_reader)
        tg.start_soon(stdin_writer)
        try:
            yield read_stream, write_stream
        finally:
            shutting_down = True
            # The shutdown sequence must run to completion even when the caller is
            # being cancelled — a cancellation that skipped it would leak the server
            # process (and its children) and could block forever on the way out.
            # Every wait inside the shield is time-bounded. The shield holds against
            # anyio-level cancellation and one native task.cancel(); a second native
            # cancel delivered mid-cleanup can still abort it — there is no
            # backend-neutral way to refuse repeated native cancellation.
            with anyio.CancelScope(shield=True):
                # Let the writer hand any message the transport already accepted to
                # the server's stdin before that stdin closes; a zero-buffer send
                # completes at the rendezvous, before the writer has written.
                write_stream.close()
                flush_deadline = anyio.current_time() + _WRITER_FLUSH_TIMEOUT
                while not writer_done.is_set() and anyio.current_time() < flush_deadline:
                    await anyio.sleep(_EXIT_POLL_INTERVAL)
                # Unblock the reader from any undelivered message so it drains
                # stdout for the rest of shutdown (see the drain note in
                # stdout_reader).
                read_stream.close()
                await _shutdown_process_tree(process)
                await _aclose_all(read_stream, write_stream, read_stream_writer, write_stream_reader)
                # Give tasks unblocked by the closes above one scheduling pass so
                # they run their exit/except paths (deterministic
                # ClosedResourceError handling) before the cancellation below.
                await anyio.lowlevel.checkpoint()
            # Nothing the pipe tasks could still do matters now; cancel them so the
            # task-group join cannot hang on a write into a pipe whose read end a
            # kill-surviving descendant still holds. Cancelling the pipe tasks' own
            # scopes, not the task group's: see the note where they are created.
            # (On the Windows fallback path a reader thread parked in a synchronous
            # ReadFile ignores cancellation and anyio waits for it; there is no
            # portable way to abandon it here.)
            reader_scope.cancel()
            writer_scope.cancel()


async def _aclose_all(*streams: AsyncResource) -> None:
    """Close every given stream."""
    for stream in streams:
        await stream.aclose()


async def _shutdown_process_tree(process: Process | FallbackProcess) -> None:
    """Shut the server process down per the MCP spec stdio sequence.

    1. Close the server's stdin so it can exit on its own.
    2. Give it `PROCESS_TERMINATION_TIMEOUT` seconds to exit.
    3. Otherwise terminate its whole process tree (SIGTERM then SIGKILL on POSIX,
       Job Object hard kill on Windows) and wait (bounded) for the death to be
       observed, logging if even that fails.
    4. Release the OS-level pipe/transport resources deterministically.
    """
    if process.stdin:  # pragma: no branch
        try:
            await process.stdin.aclose()
        except (OSError, anyio.BrokenResourceError, anyio.ClosedResourceError):
            # stdin is already closed or the pipe is already gone, which is fine
            await anyio.lowlevel.checkpoint()

    exited = await _wait_for_process_exit(process, PROCESS_TERMINATION_TIMEOUT)
    if not exited:
        # Process didn't exit from stdin closure; use platform-specific termination,
        # which kills the entire process tree, not just the spawned process.
        await _terminate_process_tree(process)
        # Wait (bounded) for the kill to be observed by the event loop: on asyncio,
        # `returncode` flips only once the child watcher's callback has been
        # delivered, and that delivery is also what lets the subprocess transport
        # close instead of leaking a ResourceWarning into whatever runs next.
        if not await _wait_for_process_exit(process, _KILL_REAP_TIMEOUT):
            # SIGKILL/job termination cannot be refused, but it can stall
            # (uninterruptible I/O, an unsignalable group member). Leave a trace
            # rather than abandoning the process silently.
            logger.warning("MCP server process %d is still alive after the kill escalation; abandoning it", process.pid)

    # On Windows, drop the process's Job Object handle now: the job is configured to
    # kill its remaining members when the handle closes, so closing it here makes
    # that reaping deterministic instead of GC-timed. (POSIX deliberately leaves a
    # well-behaved server's surviving children alive; no-op there.)
    close_process_job(process)

    # The process is dead, but its stdout pipe can still be held open by something
    # that inherited it (an orphaned grandchild, say), in which case the reader task
    # would never see EOF. Closing our wrapper poisons the Python-level reader so the
    # reader task finishes either way; the OS-level pipe end itself lives until the
    # subprocess transport is closed below.
    if process.stdout:  # pragma: no branch
        try:
            await process.stdout.aclose()
        except (OSError, anyio.BrokenResourceError, anyio.ClosedResourceError):
            # The pipe may already be broken or contended (the Windows fallback
            # closes it in a worker thread); the reader is poisoned either way.
            await anyio.lowlevel.checkpoint()

    _close_subprocess_transport(process)


def _close_subprocess_transport(process: Process | FallbackProcess) -> None:
    """Deterministically release the asyncio subprocess transport, if there is one.

    On asyncio the transport — and the OS-level pipe fds it owns — is otherwise
    closed only once the process has exited *and* every pipe has reported EOF. A
    surviving descendant that inherited a pipe end (deliberately left alive on
    POSIX when the server exited gracefully) would keep the client's fds and the
    transport open until garbage collection, which warns. Nothing public exposes
    the transport, hence the private attribute walk. trio and the Windows fallback
    close the real fds in their stream wrappers' `aclose()` and take the early
    return here.
    """
    transport = getattr(getattr(process, "_process", None), "_transport", None)
    if isinstance(transport, asyncio.SubprocessTransport):
        # If unflushed stdin bytes remain (their reader never drained them), the
        # write-pipe close stays deferred until that holder exits — close() still
        # marks the transport closed, so nothing warns at GC, and the residual fd
        # is bounded by the survivor's lifetime.
        transport.close()


async def _wait_for_process_exit(process: Process | FallbackProcess, timeout: float) -> bool:
    """Wait for the process itself to die, returning whether it did within `timeout`.

    Deliberately does not use `process.wait()`: on the asyncio backend that resolves
    only once the process has exited *and* every one of its pipes has closed — and
    pipes are inherited by the server's own children, so a well-behaved server that
    exits instantly but leaves a background child alive would be misclassified as
    hung and get its whole tree terminated. `returncode` reflects process death
    alone.
    """
    # Implemented as a plain deadline loop rather than `anyio.move_on_after()`: a
    # cancel scope's deadline fires by throwing a cancellation through every frame
    # suspended in the await chain, including the caller's, and Python 3.11's tracer
    # loses coverage events in a frame resumed after such a throw() traversal
    # (python/cpython#106749). With no cancel scope, the timeout path completes a
    # normal `sleep()` and returns, so no frame is ever thrown through.
    deadline = anyio.current_time() + timeout
    while process.returncode is None:
        if anyio.current_time() >= deadline:
            return False
        await anyio.sleep(_EXIT_POLL_INTERVAL)
    return True


def _get_executable_command(command: str) -> str:
    """Get the correct executable command normalized for the current platform.

    Args:
        command: Base command (e.g., 'uvx', 'npx')

    Returns:
        str: Platform-appropriate command
    """
    if sys.platform == "win32":  # pragma: no cover
        return get_windows_executable_command(command)
    else:  # pragma: lax no cover
        return command


async def _create_platform_compatible_process(
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    errlog: TextIO = sys.stderr,
    cwd: Path | str | None = None,
) -> Process | FallbackProcess:
    """Creates a subprocess in a platform-compatible way.

    Unix: Creates process in a new session/process group for killpg support
    Windows: Creates process in a Job Object for reliable child termination
    """
    if sys.platform == "win32":  # pragma: no cover
        return await create_windows_process(command, args, env, errlog, cwd)
    else:  # pragma: lax no cover
        return await anyio.open_process(
            [command, *args],
            env=env,
            stderr=errlog,
            cwd=cwd,
            start_new_session=True,
        )


async def _terminate_process_tree(process: Process | FallbackProcess) -> None:
    """Terminate a process and all its children using platform-specific methods.

    Unix: SIGTERM to the process group, escalating to SIGKILL after
    `FORCE_KILL_TIMEOUT`. Windows: immediate Job Object termination.
    """
    if sys.platform == "win32":  # pragma: no cover
        await terminate_windows_process_tree(process)
    else:  # pragma: lax no cover
        # Windows-only FallbackProcess never reaches the POSIX path.
        assert isinstance(process, Process)
        await terminate_posix_process_tree(process, FORCE_KILL_TIMEOUT)
