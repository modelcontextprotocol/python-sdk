"""stdio client transport: run an MCP server as a subprocess and exchange
newline-delimited JSON-RPC messages with it over stdin/stdout.

Two pipe tasks bridge the server's pipes to the session's in-memory streams.
Shutdown follows the MCP spec sequence — close the server's stdin, give it a
grace period to exit on its own, then terminate its whole process tree
(process group on POSIX, Job Object on Windows). The sequence runs inside a
cancellation shield with every wait bounded, so a cancelled caller can
neither leak a live server process nor hang on one.
"""

import logging
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal, TextIO

import anyio
import anyio.lowlevel
from anyio.abc import AsyncResource, Process
from anyio.streams.text import TextReceiveStream
from pydantic import BaseModel, Field

from mcp import types
from mcp.client._transport import TransportStreams
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

# How long the server gets to exit on its own after its stdin closes, before its
# process tree is terminated.
PROCESS_TERMINATION_TIMEOUT = 2.0

# How long the process tree gets to die after SIGTERM before it is force-killed.
# Windows tree termination is already a hard kill, so this only stretches POSIX.
FORCE_KILL_TIMEOUT = 2.0

# How long to wait for the event loop to observe the death of a killed process;
# only a process that survives even SIGKILL (uninterruptible I/O) runs this out.
_KILL_REAP_TIMEOUT = 2.0

# How long the writer task gets to flush already-accepted messages to the server's
# stdin before shutdown closes it; only a wedged pipe makes it run out.
_WRITER_FLUSH_TIMEOUT = 0.5

# How often to poll `returncode` while waiting for the process to die.
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
async def stdio_client(
    server: StdioServerParameters, errlog: TextIO = sys.stderr
) -> AsyncGenerator[TransportStreams, None]:
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
        env=get_default_environment() | (server.env or {}),
        errlog=errlog,
        cwd=server.cwd,
    )

    # The spawn succeeded; no awaits from here until the task group is entered,
    # or a cancellation delivered in the gap would leak the live process.
    read_stream_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream[SessionMessage](0)

    # Flipped by shutdown so the pipe tasks can tell expected teardown noise from
    # genuine mid-session transport failures.
    shutting_down = False
    # Set when the writer task finishes, so shutdown can wait (bounded) for already-
    # accepted messages to be flushed before it closes the server's stdin.
    writer_done = anyio.Event()

    async def stdout_reader() -> None:
        assert process.stdout, "Opened process is missing stdout"

        stdout = TextReceiveStream(process.stdout, encoding=server.encoding, errors=server.encoding_error_handler)
        try:
            async with read_stream_writer:
                try:
                    # Parse lines and deliver them over the zero-buffer stream;
                    # never read ahead while a delivery is blocked.
                    buffer = ""
                    async for chunk in stdout:
                        lines = (buffer + chunk).split("\n")
                        buffer = lines.pop()
                        for line in lines:
                            try:
                                await read_stream_writer.send(_parse_line(line))
                            except (anyio.ClosedResourceError, anyio.BrokenResourceError):
                                return  # the session is gone; only the drain below remains
                finally:
                    await _drain_stdout(process)
        except anyio.ClosedResourceError:
            pass  # our own shutdown closed the stdout stream under the read
        except (anyio.BrokenResourceError, ConnectionError):
            # The stdout pipe itself failed: expected when a shutdown kill tears
            # down a pending read, a real transport failure otherwise. Either way
            # the session sees clean closure when this task's exit closes the
            # read stream.
            if not shutting_down:
                logger.exception("Reading from the MCP server's stdout failed mid-session")

    async def stdin_writer() -> None:
        assert process.stdin, "Opened process is missing stdin"

        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    json = session_message.message.model_dump_json(by_alias=True, exclude_unset=True)
                    data = (json + "\n").encode(encoding=server.encoding, errors=server.encoding_error_handler)
                    await process.stdin.send(data)
        except (anyio.ClosedResourceError, anyio.BrokenResourceError, OSError):
            # The pipe is gone: the server died, closed its stdin, or shutdown
            # closed it under a racing write. The server may well still be alive,
            # so close the read stream to tell the session the connection is over;
            # a silently dropped write would leave its request waiting forever.
            await read_stream_writer.aclose()
        finally:
            writer_done.set()

    async def shutdown() -> None:
        """Stop traffic, flush, stop the server process, release the streams."""
        # Unblock the reader from any undelivered message: from here on it only
        # drains stdout, which a server stuck writing needs in order to get back
        # to its stdin and exit — and which lets a wedged writer's flush below
        # complete (a server blocked on stdout cannot be reading its stdin).
        read_stream.close()
        # Stop accepting messages, then give the writer a bounded window to hand
        # anything the transport already accepted to the server's stdin.
        write_stream.close()
        with anyio.move_on_after(_WRITER_FLUSH_TIMEOUT) as flush_scope:
            await writer_done.wait()
        if flush_scope.cancelled_caught:
            await anyio.lowlevel.cancel_shielded_checkpoint()  # resync coverage on 3.11 (gh-106749)
        await _stop_server_process(process)
        await _aclose_all(read_stream, write_stream, read_stream_writer, write_stream_reader)
        # One scheduling pass so tasks unblocked by the closes above exit through
        # their normal except paths before the caller cancels them.
        await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdout_reader)
        tg.start_soon(stdin_writer)
        try:
            yield read_stream, write_stream
        finally:
            shutting_down = True
            # Shutdown must finish even when the caller is being cancelled —
            # skipping it would leak the server process; every wait inside is
            # bounded. Two known limits: a native task.cancel() can still abort
            # this (the shield only holds against anyio-level cancellation), and
            # the Windows SelectorEventLoop fallback's worker threads ignore
            # cancellation while parked in synchronous pipe I/O.
            with anyio.CancelScope(shield=True):
                await shutdown()
            # Unstick the pipe tasks: a kill-surviving descendant that still holds
            # a pipe end could otherwise block the task-group join forever.
            tg.cancel_scope.cancel()
    # That cancel is delivered into this frame via throw() at the join, which
    # desyncs coverage on CPython 3.11 (gh-106749); one shielded yield resyncs it.
    await anyio.lowlevel.cancel_shielded_checkpoint()


def _parse_line(line: str) -> SessionMessage | Exception:
    """Parse one line of server stdout; parse errors are delivered to the session as values."""
    try:
        message = types.jsonrpc_message_adapter.validate_json(line, by_name=False)
    except ValueError as exc:
        logger.exception("Failed to parse JSONRPC message from server")
        return exc
    return SessionMessage(message)


async def _drain_stdout(process: ServerProcess) -> None:
    """Consume and discard the server's remaining stdout.

    Runs for the rest of shutdown so a server flushing buffered output cannot
    block on a full pipe and miss its grace-period chance to exit. Reads raw
    bytes (a dying server's flush may not be valid UTF-8); shielded so caller
    cancellation cannot skip it; ends when shutdown closes the pipe.
    """
    assert process.stdout
    with anyio.CancelScope(shield=True):
        with suppress(
            anyio.EndOfStream,
            anyio.ClosedResourceError,
            anyio.BrokenResourceError,
            ConnectionError,
            OSError,
        ):
            while True:
                await process.stdout.receive()


async def _stop_server_process(process: ServerProcess) -> None:
    """Stop the server process, leaving nothing alive and nothing leaked.

    The close-stdin, then terminate, then kill escalation order is spec text:
    https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle#shutdown
    The numeric timeouts and the tree-wide scope of the kill (process group on
    POSIX, Job Object on Windows) are SDK policy.
    """
    assert process.stdin and process.stdout, "server process is spawned with pipes"

    # Close the server's stdin so it can exit on its own, and give it a grace
    # period to do so.
    await _close_pipe(process.stdin)
    if not await _wait_for_process_exit(process, PROCESS_TERMINATION_TIMEOUT):
        await _terminate_process_tree(process)
        # Wait for the event loop to observe the death: that observation is also
        # what lets the subprocess transport close instead of warning at GC time.
        if not await _wait_for_process_exit(process, _KILL_REAP_TIMEOUT):
            logger.warning("MCP server process %d is still alive after the kill escalation; abandoning it", process.pid)

    # Closing the Job Object handle reaps surviving job members now rather than at
    # GC time; no-op on POSIX, where a graceful server's children are left alive.
    close_process_job(process)

    # A kill survivor that inherited the stdout pipe can hold it open past the
    # server's death, so the reader might never see EOF; closing our wrapper
    # poisons the reader (ending its drain) regardless.
    await _close_pipe(process.stdout)

    _close_subprocess_transport(process)


async def _close_pipe(stream: AsyncResource) -> None:
    """Close one of the process's pipe streams, tolerating a pipe that is already
    closed, broken, or contended by a worker thread."""
    with suppress(OSError, anyio.BrokenResourceError, anyio.ClosedResourceError):
        await stream.aclose()


async def _wait_for_process_exit(process: ServerProcess, timeout: float) -> bool:
    """Whether the process itself died within `timeout` seconds.

    Polls `returncode` rather than awaiting `process.wait()`: on asyncio under
    Python 3.11+, `wait()` returns only once the process has exited *and* every
    pipe has closed — and the server's own children inherit its pipes, so a
    well-behaved server that exits instantly but leaves a background child alive
    would be misclassified as hung and get its whole tree terminated.
    `returncode` reflects process death alone on every backend.
    """
    deadline = anyio.current_time() + timeout
    while process.returncode is None:
        if anyio.current_time() >= deadline:
            return False
        await anyio.sleep(_EXIT_POLL_INTERVAL)
    return True


async def _terminate_process_tree(process: ServerProcess) -> None:
    """Terminate the process and all its descendants.

    POSIX: SIGTERM to the process group, SIGKILL after `FORCE_KILL_TIMEOUT`.
    Windows: immediate Job Object termination (already a hard kill).
    """
    if sys.platform == "win32":  # pragma: no cover
        await terminate_windows_process_tree(process)
    else:  # pragma: lax no cover
        # The Windows-only FallbackProcess never reaches the POSIX path.
        assert isinstance(process, Process)
        await terminate_posix_process_tree(process, FORCE_KILL_TIMEOUT)


def _close_subprocess_transport(process: ServerProcess) -> None:
    """Deterministically release the asyncio subprocess transport, if there is one.

    On asyncio the transport (which owns the OS-level pipe fds) otherwise closes
    only once every pipe reports EOF, so a surviving descendant holding a pipe end
    would keep it open until garbage collection, which warns. Nothing public
    exposes the transport, hence the private attribute walk; trio and the Windows
    fallback close their fds in the stream wrappers and take the early return.
    """
    transport = getattr(getattr(process, "_process", None), "_transport", None)
    # Duck-typed: uvloop's UVProcessTransport is not an asyncio.SubprocessTransport.
    close = getattr(transport, "close", None)
    if callable(close):
        # CPython <= 3.12's close() can raise PermissionError re-killing a setuid
        # child; 3.13+ suppresses it internally.
        with suppress(PermissionError):
            close()


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
