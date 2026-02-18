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


def _is_jupyter_environment() -> bool:
    """Detect if code is running in a Jupyter notebook environment.

    In Jupyter environments, sys.stderr doesn't work as expected when passed
    to subprocess, so we need to handle stderr differently.

    Returns:
        bool: True if running in Jupyter/IPython notebook environment
    """
    try:
        # Check for IPython kernel
        from IPython import get_ipython  # type: ignore[reportMissingImports]

        ipython = get_ipython()  # type: ignore[reportUnknownVariableType]
        if ipython is not None:
            # Check if it's a notebook kernel (not just IPython terminal)
            if "IPKernelApp" in ipython.config:  # type: ignore[reportUnknownMemberType]
                return True
            # Also check for ZMQInteractiveShell which indicates notebook
            if ipython.__class__.__name__ == "ZMQInteractiveShell":  # type: ignore[reportUnknownMemberType]
                return True
    except (ImportError, AttributeError):
        pass
    return False


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
    The text encoding used when sending/receiving messages to the server

    defaults to utf-8
    """

    encoding_error_handler: Literal["strict", "ignore", "replace"] = "strict"
    """
    The text encoding error handler.

    See https://docs.python.org/3/library/codecs.html#codec-base-classes for
    explanations of possible values
    """


@asynccontextmanager
async def stdio_client(server: StdioServerParameters, errlog: TextIO = sys.stderr):
    """Client transport for stdio: this will connect to a server by spawning a
    process and communicating with it over stdin/stdout.

    Args:
        server: Parameters for the server process
        errlog: TextIO stream for stderr output. In Jupyter environments,
                stderr is captured and printed to work around Jupyter's
                limitations with subprocess stderr handling.
    """
    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]

    write_stream: MemoryObjectSendStream[SessionMessage]
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    # Detect Jupyter environment for stderr handling
    is_jupyter = _is_jupyter_environment()

    try:
        command = _get_executable_command(server.command)

        # Open process with stderr handling based on environment
        process = await _create_platform_compatible_process(
            command=command,
            args=server.args,
            env=({**get_default_environment(), **server.env} if server.env is not None else get_default_environment()),
            errlog=errlog,
            cwd=server.cwd,
            capture_stderr=is_jupyter,
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

    async def stderr_reader():
        """Read stderr from the process and print it to notebook output.

        In Jupyter environments, stderr is captured as a pipe and printed
        to make it visible in the notebook output.

        See: https://github.com/modelcontextprotocol/python-sdk/issues/156
        """
        if not process.stderr:
            return  # pragma: no cover

        try:
            async for chunk in TextReceiveStream(
                process.stderr,
                encoding=server.encoding,
                errors=server.encoding_error_handler,
            ):
                # Use ANSI red color for stderr visibility in Jupyter
                print(f"\033[91m{chunk}\033[0m", end="", flush=True)
        except anyio.ClosedResourceError:  # pragma: no cover
            await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as tg, process:
        tg.start_soon(stdout_reader)
        tg.start_soon(stdin_writer)
        # Only start stderr reader if we're capturing stderr (Jupyter mode)
        if is_jupyter and process.stderr:
            tg.start_soon(stderr_reader)
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
    capture_stderr: bool = False,
):
    """Creates a subprocess in a platform-compatible way.

    Unix: Creates process in a new session/process group for killpg support
    Windows: Creates process in a Job Object for reliable child termination

    Args:
        command: The executable command to run
        args: Command line arguments
        env: Environment variables for the process
        errlog: TextIO stream for stderr (used when capture_stderr=False)
        cwd: Working directory for the process
        capture_stderr: If True, stderr is captured as a pipe for async reading.
                       This is needed for Jupyter environments where passing
                       sys.stderr directly doesn't work properly.

    Returns:
        Process with stdin, stdout, and optionally stderr streams
    """
    # Determine stderr handling: PIPE for capture, or redirect to errlog
    stderr_target = subprocess.PIPE if capture_stderr else errlog

    if sys.platform == "win32":  # pragma: no cover
        process = await create_windows_process(command, args, env, stderr_target, cwd)
    else:  # pragma: lax no cover
        process = await anyio.open_process(
            [command, *args],
            env=env,
            stderr=stderr_target,
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
