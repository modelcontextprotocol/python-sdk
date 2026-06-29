"""stdio client transport.

Runs an MCP server as a subprocess and exchanges newline-delimited JSON-RPC
messages with it over stdin/stdout. Two pipe tasks bridge the server's pipes
to the session's in-memory streams; shutdown follows the MCP spec sequence
(close stdin, wait, then kill the process tree) inside a cancellation shield
with every wait bounded, so a cancelled caller can neither leak a live server
process nor hang on one.
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
import mcp_types as types
from anyio.abc import AsyncResource, Process
from anyio.streams.text import TextReceiveStream
from pydantic import BaseModel, Field

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

# Grace period for the server to exit on its own after its stdin closes.
PROCESS_TERMINATION_TIMEOUT = 2.0

# Extra time after SIGTERM before SIGKILL; POSIX only (Windows kills hard).
FORCE_KILL_TIMEOUT = 2.0

# Time for the event loop to observe a kill; only an unkillable process runs this out.
_KILL_REAP_TIMEOUT = 2.0

# Time for the writer to flush accepted messages before stdin closes.
_WRITER_FLUSH_TIMEOUT = 0.5

# How often to poll returncode while waiting for the process to die.
_EXIT_POLL_INTERVAL = 0.01


def get_default_environment() -> dict[str, str]:
    """Returns only the environment variables that are safe to inherit."""
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
    """Extra environment variables, merged over get_default_environment()."""

    cwd: str | Path | None = None
    """The working directory to use when spawning the process."""

    encoding: str = "utf-8"
    """Text encoding for messages to and from the server."""

    encoding_error_handler: Literal["strict", "ignore", "replace"] = "strict"
    """Encoding error handler; see https://docs.python.org/3/library/codecs.html#error-handlers."""


@asynccontextmanager
async def stdio_client(
    server: StdioServerParameters, errlog: TextIO = sys.stderr
) -> AsyncGenerator[TransportStreams, None]:
    """Spawns an MCP server subprocess and connects to it over stdin/stdout.

    Raises:
        OSError: If the server process cannot be spawned.
        ValueError: If the spawn parameters are invalid (embedded NUL bytes).
    """
    command = _get_executable_command(server.command)

    process = await _create_platform_compatible_process(
        command=command,
        args=server.args,
        env=get_default_environment() | (server.env or {}),
        errlog=errlog,
        cwd=server.cwd,
    )

    # The spawn succeeded; no awaits until the task group is entered, or a
    # cancellation delivered in the gap would leak the live process.
    read_stream_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream[SessionMessage](0)

    shutting_down = False
    writer_done = anyio.Event()

    async def stdout_reader() -> None:
        assert process.stdout, "Opened process is missing stdout"

        stdout = TextReceiveStream(process.stdout, encoding=server.encoding, errors=server.encoding_error_handler)
        try:
            async with read_stream_writer:
                try:
                    # One line at a time; no read-ahead while a delivery is blocked.
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
            # Teardown noise during shutdown, a real failure otherwise; either way
            # the session sees clean closure when the read stream closes.
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
            # The server may still be alive: close the read stream so the session
            # sees the connection end instead of a request hanging forever.
            await read_stream_writer.aclose()
        finally:
            writer_done.set()

    async def shutdown() -> None:
        """Winds the transport down: stop traffic, flush, stop the server, release the streams."""
        # Unblock the reader into its drain: a server stuck writing stdout cannot
        # read its stdin, so draining is what lets the flush below complete.
        read_stream.close()
        # Bounded window for the writer to flush already-accepted messages.
        write_stream.close()
        with anyio.move_on_after(_WRITER_FLUSH_TIMEOUT) as flush_scope:
            await writer_done.wait()
        if flush_scope.cancelled_caught:
            await anyio.lowlevel.cancel_shielded_checkpoint()  # resync coverage on 3.11 (gh-106749)
        await _stop_server_process(process)
        await _aclose_all(read_stream, write_stream, read_stream_writer, write_stream_reader)
        # One pass so unblocked tasks exit via their except paths before the cancel.
        await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdout_reader)
        tg.start_soon(stdin_writer)
        try:
            yield read_stream, write_stream
        finally:
            shutting_down = True
            # Shutdown must finish even under caller cancellation, or the server
            # process would leak; every wait inside is bounded. (Native
            # task.cancel() and the fallback's worker threads can still defeat it.)
            with anyio.CancelScope(shield=True):
                await shutdown()
            # Unstick pipe tasks a kill survivor's open pipe end could still block.
            tg.cancel_scope.cancel()
    # The cancel lands via throw(); one yield resyncs 3.11 coverage (gh-106749).
    await anyio.lowlevel.cancel_shielded_checkpoint()


def _parse_line(line: str) -> SessionMessage | Exception:
    """Parses one stdout line, returning parse errors as values for the session to surface."""
    try:
        message = types.jsonrpc_message_adapter.validate_json(line, by_name=False)
    except ValueError as exc:
        logger.exception("Failed to parse JSONRPC message from server")
        return exc
    return SessionMessage(message)


async def _drain_stdout(process: ServerProcess) -> None:
    """Consumes and discards the server's remaining stdout.

    Keeps a server flushing buffered output from blocking on a full pipe and
    missing its chance to exit; shielded, raw bytes, ends when shutdown closes
    the pipe.
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
    """Closes stdin, waits out the grace period, then kills the whole tree.

    The escalation order is spec text; timeouts and tree-wide scope are SDK policy:
    https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle#shutdown
    """
    assert process.stdin and process.stdout, "server process is spawned with pipes"

    await _close_pipe(process.stdin)
    if not await _wait_for_process_exit(process, PROCESS_TERMINATION_TIMEOUT):
        await _terminate_process_tree(process)
        # Until the event loop observes the death, the transport cannot close.
        if not await _wait_for_process_exit(process, _KILL_REAP_TIMEOUT):
            logger.warning("MCP server process %d is still alive after the kill escalation; abandoning it", process.pid)

    # Reaps surviving Windows job members now, not at GC; no-op on POSIX.
    close_process_job(process)
    # A kill survivor can hold the stdout pipe open; poison the reader anyway.
    await _close_pipe(process.stdout)
    _close_subprocess_transport(process)


async def _close_pipe(stream: AsyncResource) -> None:
    """Closes a pipe stream, tolerating one already closed, broken, or contended."""
    with suppress(OSError, anyio.BrokenResourceError, anyio.ClosedResourceError):
        await stream.aclose()


async def _wait_for_process_exit(process: ServerProcess, timeout: float) -> bool:
    """Returns whether the process died within the timeout, by polling returncode.

    Not process.wait(): on asyncio 3.11+ it also waits for pipe EOF, and a
    child that inherited the pipes makes an exited server look hung.
    """
    deadline = anyio.current_time() + timeout
    while process.returncode is None:
        if anyio.current_time() >= deadline:
            return False
        await anyio.sleep(_EXIT_POLL_INTERVAL)
    return True


async def _terminate_process_tree(process: ServerProcess) -> None:
    """Kills the process and all its descendants.

    POSIX: SIGTERM to the process group, SIGKILL after FORCE_KILL_TIMEOUT.
    Windows: immediate Job Object termination (already a hard kill).
    """
    if sys.platform == "win32":  # pragma: no cover
        await terminate_windows_process_tree(process)
    else:  # pragma: lax no cover
        # The Windows-only FallbackProcess never reaches the POSIX path.
        assert isinstance(process, Process)
        await terminate_posix_process_tree(process, FORCE_KILL_TIMEOUT)


def _close_subprocess_transport(process: ServerProcess) -> None:
    """Closes the asyncio subprocess transport, if there is one.

    The transport otherwise stays open (and warns at GC) while a surviving
    descendant holds a pipe end; nothing public exposes it, hence the attribute
    walk. No-op on trio and the Windows fallback.
    """
    transport = getattr(getattr(process, "_process", None), "_transport", None)
    # Duck-typed: uvloop's UVProcessTransport is not an asyncio.SubprocessTransport.
    close = getattr(transport, "close", None)
    if callable(close):
        # close() on <=3.12 can raise PermissionError re-killing a setuid child.
        with suppress(PermissionError):
            close()


def _get_executable_command(command: str) -> str:
    """Normalizes the command for the current platform."""
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
    """Spawns the server in its own kill scope.

    A new session/process group on POSIX, a Job Object on Windows.
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
    """Closes every given stream."""
    for stream in streams:
        await stream.aclose()
