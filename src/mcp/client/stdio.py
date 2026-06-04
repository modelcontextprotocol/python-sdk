import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager, suppress
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
    ServerProcess,
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

# How long the process tree gets to die after SIGTERM before it is force-killed.
# Windows tree termination is already a hard kill, so this only stretches POSIX.
FORCE_KILL_TIMEOUT = 2.0

# How long to wait for the event loop to observe the death of a killed process; only
# a process that even SIGKILL cannot collect (uninterruptible I/O) runs this out.
_KILL_REAP_TIMEOUT = 2.0

# How long the writer task gets to flush already-accepted outbound messages to the
# server's stdin before shutdown closes it; only a wedged pipe (full, with its
# reader gone) makes it run out.
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

    Raises:
        OSError: If the server process cannot be spawned (for example, the command
            does not exist or is not executable).
        ValueError: If the spawn parameters are invalid (for example, an embedded
            NUL byte in the command or an argument).
    """
    command = _get_executable_command(server.command)

    process = await _create_platform_compatible_process(
        command=command,
        args=server.args,
        env=({**get_default_environment(), **server.env} if server.env is not None else get_default_environment()),
        errlog=errlog,
        cwd=server.cwd,
    )

    # The spawn succeeded; from here until the task group is entered there must be
    # no await — a cancellation delivered in that gap would leak the live process.
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]
    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)

    write_stream: MemoryObjectSendStream[SessionMessage]
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage]
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    # Flipped by the shutdown sequence so the pipe tasks can tell expected
    # teardown noise from genuine mid-session transport failures.
    shutting_down = False
    # Set when stdin_writer finishes, so shutdown can wait (bounded) for messages
    # the transport already accepted to be flushed before it closes stdin.
    writer_done = anyio.Event()

    async def stdout_reader() -> None:
        assert process.stdout, "Opened process is missing stdout"

        stdout = TextReceiveStream(
            process.stdout,
            encoding=server.encoding,
            errors=server.encoding_error_handler,
        )
        try:
            async with read_stream_writer:
                # Phase 1: parse one line at a time and deliver it over the
                # zero-buffer stream; no read-ahead while a send is blocked.
                buffer = ""
                try:
                    async for chunk in stdout:
                        lines = (buffer + chunk).split("\n")
                        buffer = lines.pop()
                        for line in lines:
                            await read_stream_writer.send(_parse_line(line))
                except (anyio.ClosedResourceError, anyio.BrokenResourceError):
                    # The read stream is gone (shutdown closed it, or the caller did).
                    # Phase 2: keep consuming stdout without delivering, so a server
                    # flushing its remaining output during shutdown does not block on
                    # a full pipe and miss its chance to exit within the grace period.
                    with suppress(anyio.EndOfStream):
                        while True:
                            await stdout.receive()
        except anyio.ClosedResourceError:
            # Our own shutdown closed/poisoned the stdout stream under the read.
            pass
        except (anyio.BrokenResourceError, ConnectionError):
            # The stdout pipe itself failed; a shutdown kill can tear down a pending
            # read (ConnectionResetError on the proactor backend), while mid-session
            # it is a real transport failure worth a log line. Either way the session
            # observes a clean closure when this task's exit closes the read stream.
            if not shutting_down:
                logger.exception("Reading from the MCP server's stdout failed mid-session")

    async def stdin_writer() -> None:
        assert process.stdin, "Opened process is missing stdin"

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
            # The pipe is gone: the server died, closed its stdin, or shutdown closed
            # it under a racing write (the exact exception varies by platform and
            # backend). The server may well still be alive, so close the read stream
            # to tell the session the connection is over; a silently swallowed write
            # would leave a request waiting forever for its response.
            await read_stream_writer.aclose()
        finally:
            writer_done.set()

    async def shutdown() -> None:
        """Wind the transport down, leaving no live server process behind.

        1. Close the session's write stream, then wait (bounded by
           `_WRITER_FLUSH_TIMEOUT`) for the writer task to hand any message the
           transport already accepted to the server's stdin before that stdin
           closes; a zero-buffer send completes at the rendezvous, before the
           writer has written.
        2. Close the session's read stream, unblocking the reader from any
           undelivered message so it drains stdout for the rest of shutdown
           (see the drain note in `stdout_reader`).
        3. Stop the server process: close its stdin, give it a grace period to
           exit on its own, and terminate its process tree if it does not
           (see `_stop_server_process`).
        4. Close every transport stream.
        5. Give tasks unblocked by the closes above one scheduling pass so they
           run their exit/except paths (deterministic ClosedResourceError
           handling) before the caller cancels them.
        """
        write_stream.close()
        with anyio.move_on_after(_WRITER_FLUSH_TIMEOUT) as flush_scope:
            await writer_done.wait()
        if flush_scope.cancelled_caught:
            await anyio.lowlevel.cancel_shielded_checkpoint()  # heal gh-106749
        read_stream.close()
        await _stop_server_process(process)
        await _aclose_all(read_stream, write_stream, read_stream_writer, write_stream_reader)
        await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdout_reader)
        tg.start_soon(stdin_writer)
        try:
            yield read_stream, write_stream
        finally:
            shutting_down = True
            # Shutdown must run to completion even when the caller is being
            # cancelled (skipping it would leak the server process); every wait
            # inside the shield is time-bounded. A native task.cancel() delivered
            # mid-cleanup can still abort it: the shield only holds against
            # anyio-level cancellation.
            with anyio.CancelScope(shield=True):
                await shutdown()
            # Cancel the pipe tasks so the join cannot hang on a write into a pipe
            # whose read end a kill-surviving descendant still holds. (The Windows
            # fallback's reader thread parked in a synchronous ReadFile ignores
            # cancellation; anyio waits for it, with no portable way to abandon it.)
            tg.cancel_scope.cancel()
    # The cancel above is delivered via `coro.throw()` into this task at
    # the task-group join; on CPython 3.11 (gh-106749) that drops `'call'`
    # trace events for the outer await chain and desyncs coverage's CTracer
    # past the caller's frame. Yielding once here resumes via `.send()`,
    # which re-stamps the missing `'call'` events and resyncs the tracer.
    # Shielded so a pending outer cancel is not re-delivered at this point.
    await anyio.lowlevel.cancel_shielded_checkpoint()


def _parse_line(line: str) -> SessionMessage | Exception:
    """Parse one line of server stdout; parse errors are delivered to the session as values."""
    try:
        message = types.jsonrpc_message_adapter.validate_json(line, by_name=False)
    except ValueError as exc:
        logger.exception("Failed to parse JSONRPC message from server")
        return exc
    return SessionMessage(message)


async def _stop_server_process(process: ServerProcess) -> None:
    """Stop the server process following the MCP stdio shutdown sequence.

    The close-stdin, then SIGTERM, then SIGKILL escalation order is spec text:
    https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle#shutdown
    The numeric timeouts and the tree-wide scope of the kill (process group on
    POSIX, Job Object on Windows, not just the spawned process) are SDK policy.

    1. Close the server's stdin so it can exit on its own.
    2. Give it `PROCESS_TERMINATION_TIMEOUT` seconds to exit.
    3. Otherwise terminate its whole process tree and wait (bounded) for the
       death to be observed, logging if even that fails.
    4. Release the OS-level pipe/transport resources deterministically.
    """
    if process.stdin:  # pragma: no branch
        try:
            await process.stdin.aclose()
        except (OSError, anyio.BrokenResourceError, anyio.ClosedResourceError):
            # stdin is already closed or the pipe is already gone, which is fine
            pass

    exited = await _wait_for_process_exit(process, PROCESS_TERMINATION_TIMEOUT)
    if not exited:
        await _terminate_process_tree(process)
        # Wait (bounded) for the kill to be observed by the event loop: on asyncio,
        # `returncode` flips only once the child watcher's callback has been
        # delivered, and that delivery is also what lets the subprocess transport
        # close instead of leaking a ResourceWarning into whatever runs next.
        if not await _wait_for_process_exit(process, _KILL_REAP_TIMEOUT):
            # SIGKILL/job termination cannot be refused, but it can stall
            # (uninterruptible I/O, an unsignalable group member); leave a trace
            # rather than abandoning the process silently.
            logger.warning("MCP server process %d is still alive after the kill escalation; abandoning it", process.pid)

    # Drop the Job Object handle now so Windows reaps surviving job members
    # deterministically instead of at GC time (see `close_process_job`); no-op
    # on POSIX, which deliberately leaves a graceful server's children alive.
    close_process_job(process)

    # Something that inherited the stdout pipe (an orphaned grandchild, say) can
    # hold it open past the process's death, so the reader might never see EOF.
    # Closing our wrapper poisons the Python-level reader either way; the OS-level
    # pipe end itself lives until the transport close below.
    if process.stdout:  # pragma: no branch
        try:
            await process.stdout.aclose()
        except (OSError, anyio.BrokenResourceError, anyio.ClosedResourceError):
            # The pipe may already be broken or contended (the Windows fallback
            # closes it in a worker thread); the reader is poisoned either way.
            pass

    _close_subprocess_transport(process)


async def _wait_for_process_exit(process: ServerProcess, timeout: float) -> bool:
    """Wait for the process itself to die, returning whether it did within `timeout`.

    Deliberately does not use `process.wait()`: on asyncio under Python 3.11+ it
    resolves only once the process has exited *and* every one of its pipes has
    closed (3.10 and trio resolve on exit alone), and pipes are inherited by the
    server's own children, so a well-behaved server that exits instantly but leaves
    a background child alive would be misclassified as hung and get its whole tree
    terminated. `returncode` reflects process death alone on every backend.
    """
    with anyio.move_on_after(timeout):
        while process.returncode is None:
            await anyio.sleep(_EXIT_POLL_INTERVAL)
        return True
    await anyio.lowlevel.cancel_shielded_checkpoint()  # heal gh-106749 after the throw
    return False


async def _terminate_process_tree(process: ServerProcess) -> None:
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


def _close_subprocess_transport(process: ServerProcess) -> None:
    """Deterministically release the asyncio subprocess transport, if there is one.

    On asyncio the transport (and the OS-level pipe fds it owns) is otherwise
    closed only once the process has exited and every pipe has reported EOF. A
    surviving descendant that inherited a pipe end (deliberately left alive on
    POSIX when the server exited gracefully) would keep the fds and the transport
    open until garbage collection, which warns. Nothing public exposes the
    transport, hence the private attribute walk. trio and the Windows fallback
    close the real fds in their stream wrappers' `aclose()` and take the early
    return here.
    """
    transport = getattr(getattr(process, "_process", None), "_transport", None)
    if isinstance(transport, asyncio.SubprocessTransport):
        # Unflushed stdin bytes defer the write-pipe close until their holder
        # exits, but close() still marks the transport closed, so nothing warns
        # at GC and the residual fd is bounded by the survivor's lifetime.
        transport.close()


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
) -> ServerProcess:
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


async def _aclose_all(*streams: AsyncResource) -> None:
    """Close every given stream."""
    for stream in streams:
        await stream.aclose()
