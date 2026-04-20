import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, TextIO

import anyio
import anyio.lowlevel
import sniffio
from anyio.abc import Process
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from anyio.streams.text import TextReceiveStream
from pydantic import BaseModel, Field

from mcp import types
from mcp.os.posix.utilities import terminate_posix_process_tree
from mcp.os.win32.utilities import (
    FallbackProcess,
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

# Timeout for process termination before falling back to force kill
PROCESS_TERMINATION_TIMEOUT = 2.0


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
async def _asyncio_background_tasks(
    stdout_reader: Callable[[], Coroutine[Any, Any, None]],
    stdin_writer: Callable[[], Coroutine[Any, Any, None]],
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception],
    write_stream: MemoryObjectSendStream[SessionMessage],
) -> AsyncIterator[None]:
    """Spawn the stdio reader/writer as top-level asyncio tasks (see #577).

    The tasks are detached from the caller's cancel-scope stack, which
    is what lets callers clean up multiple transports in arbitrary
    order without tripping anyio's LIFO cancel-scope check.

    If a background task crashes while the caller is still inside the
    yield, the memory streams are closed via ``add_done_callback`` so
    in-flight reads wake up with ``ClosedResourceError`` instead of
    hanging forever. Any non-cancellation, non-closed-resource
    exception from the tasks is re-raised on exit so crashes do not
    go unnoticed — matching the exception propagation an anyio task
    group would have given.
    """

    def _on_done(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        logger.debug(
            "stdio_client background task raised %s — closing streams to wake up caller",
            type(exc).__name__,
            exc_info=exc,
        )
        for stream in (read_stream_writer, write_stream):
            try:
                stream.close()
            except Exception:  # pragma: no cover
                pass

    stdout_task: asyncio.Task[None] = asyncio.create_task(stdout_reader())
    stdin_task: asyncio.Task[None] = asyncio.create_task(stdin_writer())
    stdout_task.add_done_callback(_on_done)
    stdin_task.add_done_callback(_on_done)
    tasks = (stdout_task, stdin_task)
    try:
        yield
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        pending_exc: BaseException | None = None
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except anyio.ClosedResourceError:
                pass
            except BaseException as exc:  # noqa: BLE001
                if pending_exc is None:
                    pending_exc = exc
        if pending_exc is not None:
            raise pending_exc


@asynccontextmanager
async def _anyio_task_group_background(
    stdout_reader: Callable[[], Coroutine[Any, Any, None]],
    stdin_writer: Callable[[], Coroutine[Any, Any, None]],
) -> AsyncIterator[None]:
    """Structured-concurrency fallback for backends other than asyncio.

    Trio forbids orphan tasks by design, so the historical task-group
    pattern is retained here. Callers on trio must clean up multiple
    transports in LIFO order; cross-task cleanup (#577) cannot be
    fixed on that backend without violating its concurrency model.
    """
    async with anyio.create_task_group() as tg:
        tg.start_soon(stdout_reader)
        tg.start_soon(stdin_writer)
        yield


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
    except OSError:
        # Clean up streams if process creation fails
        await read_stream.aclose()
        await write_stream.aclose()
        await read_stream_writer.aclose()
        await write_stream_reader.aclose()
        raise

    async def stdout_reader():
        assert process.stdout, "Opened process is missing stdout"

        try:
            async with read_stream_writer:
                buffer = ""
                async for chunk in TextReceiveStream(
                    process.stdout,
                    encoding=server.encoding,
                    errors=server.encoding_error_handler,
                ):
                    lines = (buffer + chunk).split("\n")
                    buffer = lines.pop()

                    for line in lines:
                        try:
                            message = types.jsonrpc_message_adapter.validate_json(line, by_name=False)
                        except Exception as exc:  # pragma: no cover
                            logger.exception("Failed to parse JSONRPC message from server")
                            await read_stream_writer.send(exc)
                            continue

                        session_message = SessionMessage(message)
                        await read_stream_writer.send(session_message)
        except anyio.ClosedResourceError:  # pragma: lax no cover
            await anyio.lowlevel.checkpoint()

    async def stdin_writer():
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
        except anyio.ClosedResourceError:  # pragma: no cover
            await anyio.lowlevel.checkpoint()

    async def _cleanup_process_and_streams() -> None:
        # MCP spec: stdio shutdown sequence
        # 1. Close input stream to server
        # 2. Wait for server to exit, or send SIGTERM if it doesn't exit in time
        # 3. Send SIGKILL if still not exited
        if process.stdin:  # pragma: no branch
            try:
                await process.stdin.aclose()
            except Exception:  # pragma: no cover
                # stdin might already be closed, which is fine
                pass

        try:
            # Give the process time to exit gracefully after stdin closes
            with anyio.fail_after(PROCESS_TERMINATION_TIMEOUT):
                await process.wait()
        except TimeoutError:
            # Process didn't exit from stdin closure, use platform-specific termination
            # which handles SIGTERM -> SIGKILL escalation
            await _terminate_process_tree(process)
        except ProcessLookupError:  # pragma: no cover
            # Process already exited, which is fine
            pass
        await read_stream.aclose()
        await write_stream.aclose()
        await read_stream_writer.aclose()
        await write_stream_reader.aclose()

    # On asyncio we spawn the reader / writer with asyncio.create_task rather
    # than an anyio task group, so their cancel scopes are not bound to the
    # caller's task. That is what lets callers clean up multiple transports
    # in arbitrary order — see #577. On structured-concurrency backends
    # (trio), we keep the task group: orphan tasks are disallowed there by
    # design, and cross-task cleanup is fundamentally incompatible with
    # that model, so callers on trio still have to clean up LIFO.
    if sniffio.current_async_library() == "asyncio":
        bg_cm = _asyncio_background_tasks(stdout_reader, stdin_writer, read_stream_writer, write_stream)
    else:
        bg_cm = _anyio_task_group_background(stdout_reader, stdin_writer)

    async with bg_cm, process:
        try:
            yield read_stream, write_stream
        finally:
            await _cleanup_process_and_streams()


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
):
    """Creates a subprocess in a platform-compatible way.

    Unix: Creates process in a new session/process group for killpg support
    Windows: Creates process in a Job Object for reliable child termination
    """
    if sys.platform == "win32":  # pragma: no cover
        process = await create_windows_process(command, args, env, errlog, cwd)
    else:  # pragma: lax no cover
        process = await anyio.open_process(
            [command, *args],
            env=env,
            stderr=errlog,
            cwd=cwd,
            start_new_session=True,
        )

    return process


async def _terminate_process_tree(process: Process | FallbackProcess, timeout_seconds: float = 2.0) -> None:
    """Terminate a process and all its children using platform-specific methods.

    Unix: Uses os.killpg() for atomic process group termination
    Windows: Uses Job Objects via pywin32 for reliable child process cleanup

    Args:
        process: The process to terminate
        timeout_seconds: Timeout in seconds before force killing (default: 2.0)
    """
    if sys.platform == "win32":  # pragma: no cover
        await terminate_windows_process_tree(process, timeout_seconds)
    else:  # pragma: lax no cover
        # FallbackProcess should only be used for Windows compatibility
        assert isinstance(process, Process)
        await terminate_posix_process_tree(process, timeout_seconds)
