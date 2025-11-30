import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, TextIO

import anyio
import anyio.lowlevel
from anyio.abc import Process
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from anyio.streams.text import TextReceiveStream
from pydantic import BaseModel, Field

import mcp.types as types
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


def _is_jupyter_notebook() -> bool:
    """
    Detect if running in a Jupyter notebook or IPython environment.

    Returns:
        bool: True if running in Jupyter/IPython, False otherwise
    """
    try:
        from IPython import get_ipython  # type: ignore[import-not-found]

        ipython = get_ipython()  # type: ignore[no-untyped-call]
        return ipython is not None and ipython.__class__.__name__ in ("ZMQInteractiveShell", "TerminalInteractiveShell")  # type: ignore[union-attr]
    except ImportError:
        return False


def _print_stderr(line: str, errlog: TextIO) -> None:
    """
    Print stderr output, using IPython's display system if in Jupyter notebook.

    Args:
        line: The line to print
        errlog: The fallback TextIO stream (used when not in Jupyter)
    """
    if _is_jupyter_notebook():
        try:
            from IPython.display import HTML, display  # type: ignore[import-not-found]

            # Use IPython's display system with red color for stderr
            # This ensures proper rendering in Jupyter notebooks
            display(HTML(f'<pre style="color: red;">{line}</pre>'))  # type: ignore[no-untyped-call]
        except Exception:
            # If IPython display fails, fall back to regular print
            # Log the error but continue (non-critical)
            logger.debug("Failed to use IPython display for stderr, falling back to print", exc_info=True)
            print(line, file=errlog)
    else:
        # Not in Jupyter, use standard stderr redirection
        print(line, file=errlog)


def get_default_environment() -> dict[str, str]:
    """
    Returns a default environment object including only environment variables deemed
    safe to inherit.
    """
    env: dict[str, str] = {}

    for key in DEFAULT_INHERITED_ENV_VARS:
        value = os.environ.get(key)
        if value is None:
            continue  # pragma: no cover

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
    The text encoding used when sending/receiving messages to the server

    defaults to utf-8
    """

    encoding_error_handler: Literal["strict", "ignore", "replace"] = "strict"
    """
    The text encoding error handler.

    See https://docs.python.org/3/library/codecs.html#codec-base-classes for
    explanations of possible values
    """


async def _stdout_reader(
    process: Process | FallbackProcess,
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception],
    encoding: str,
    encoding_error_handler: str,
):
    """Read stdout from the process and parse JSONRPC messages."""
    assert process.stdout, "Opened process is missing stdout"

    try:
        async with read_stream_writer:
            buffer = ""
            async for chunk in TextReceiveStream(
                process.stdout,
                encoding=encoding,
                errors=encoding_error_handler,
            ):
                lines = (buffer + chunk).split("\n")
                buffer = lines.pop()

                for line in lines:
                    try:
                        message = types.JSONRPCMessage.model_validate_json(line)
                    except Exception as exc:  # pragma: no cover
                        logger.exception("Failed to parse JSONRPC message from server")
                        await read_stream_writer.send(exc)
                        continue

                    session_message = SessionMessage(message)
                    await read_stream_writer.send(session_message)
    except anyio.ClosedResourceError:  # pragma: no cover
        await anyio.lowlevel.checkpoint()


async def _stdin_writer(
    process: Process | FallbackProcess,
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage],
    encoding: str,
    encoding_error_handler: str,
):
    """Write session messages to the process stdin."""
    assert process.stdin, "Opened process is missing stdin"

    try:
        async with write_stream_reader:
            async for session_message in write_stream_reader:
                json = session_message.message.model_dump_json(by_alias=True, exclude_none=True)
                await process.stdin.send(
                    (json + "\n").encode(
                        encoding=encoding,
                        errors=encoding_error_handler,
                    )
                )
    except anyio.ClosedResourceError:  # pragma: no cover
        await anyio.lowlevel.checkpoint()


async def _stderr_reader(
    process: Process | FallbackProcess,
    errlog: TextIO,
    encoding: str,
    encoding_error_handler: str,
):
    """Read stderr from the process and display it appropriately."""
    if not process.stderr:
        return

    try:
        buffer = ""
        async for chunk in TextReceiveStream(
            process.stderr,
            encoding=encoding,
            errors=encoding_error_handler,
        ):
            lines = (buffer + chunk).split("\n")
            buffer = lines.pop()

            for line in lines:
                if line.strip():  # Only print non-empty lines
                    try:
                        _print_stderr(line, errlog)
                    except Exception:
                        # Log errors but continue (non-critical)
                        logger.debug("Failed to print stderr line", exc_info=True)

        # Print any remaining buffer content
        if buffer.strip():
            try:
                _print_stderr(buffer, errlog)
            except Exception:
                logger.debug("Failed to print final stderr buffer", exc_info=True)
    except anyio.ClosedResourceError:  # pragma: no cover
        await anyio.lowlevel.checkpoint()
    except Exception:
        # Log errors but continue (non-critical)
        logger.debug("Error reading stderr", exc_info=True)


@asynccontextmanager
async def stdio_client(server: StdioServerParameters, errlog: TextIO = sys.stderr):
    """
    Client transport for stdio: this will connect to a server by spawning a
    process and communicating with it over stdin/stdout.

    This function automatically handles stderr output in a way that is compatible
    with Jupyter notebook environments. When running in Jupyter, stderr output
    is displayed using IPython's display system with red color formatting.
    When not in Jupyter, stderr is redirected to the provided errlog stream
    (defaults to sys.stderr).

    Args:
        server: Parameters for the server process to spawn
        errlog: TextIO stream for stderr output when not in Jupyter (defaults to sys.stderr).
                This parameter is kept for backward compatibility but may be ignored
                when running in Jupyter notebook environments.
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

    async with (
        anyio.create_task_group() as tg,
        process,
    ):
        tg.start_soon(_stdout_reader, process, read_stream_writer, server.encoding, server.encoding_error_handler)
        tg.start_soon(_stdin_writer, process, write_stream_reader, server.encoding, server.encoding_error_handler)
        if process.stderr:
            tg.start_soon(_stderr_reader, process, errlog, server.encoding, server.encoding_error_handler)
        try:
            yield read_stream, write_stream
        finally:
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


def _get_executable_command(command: str) -> str:
    """
    Get the correct executable command normalized for the current platform.

    Args:
        command: Base command (e.g., 'uvx', 'npx')

    Returns:
        str: Platform-appropriate command
    """
    if sys.platform == "win32":  # pragma: no cover
        return get_windows_executable_command(command)
    else:
        return command  # pragma: no cover


async def _create_platform_compatible_process(
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    errlog: TextIO = sys.stderr,
    cwd: Path | str | None = None,
):
    """
    Creates a subprocess in a platform-compatible way.

    Unix: Creates process in a new session/process group for killpg support
    Windows: Creates process in a Job Object for reliable child termination

    Note: stderr is piped (not redirected) to allow async reading for Jupyter
    notebook compatibility. The errlog parameter is kept for backward compatibility
    but is only used when not in Jupyter environments.
    """
    if sys.platform == "win32":  # pragma: no cover
        process = await create_windows_process(command, args, env, errlog, cwd, pipe_stderr=True)
    else:
        # Pipe stderr instead of redirecting to allow async reading
        process = await anyio.open_process(
            [command, *args],
            env=env,
            stderr=subprocess.PIPE,
            cwd=cwd,
            start_new_session=True,
        )  # pragma: no cover

    return process


async def _terminate_process_tree(process: Process | FallbackProcess, timeout_seconds: float = 2.0) -> None:
    """
    Terminate a process and all its children using platform-specific methods.

    Unix: Uses os.killpg() for atomic process group termination
    Windows: Uses Job Objects via pywin32 for reliable child process cleanup

    Args:
        process: The process to terminate
        timeout_seconds: Timeout in seconds before force killing (default: 2.0)
    """
    if sys.platform == "win32":  # pragma: no cover
        await terminate_windows_process_tree(process, timeout_seconds)
    else:  # pragma: no cover
        # FallbackProcess should only be used for Windows compatibility
        assert isinstance(process, Process)
        await terminate_posix_process_tree(process, timeout_seconds)
