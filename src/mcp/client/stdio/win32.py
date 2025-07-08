"""
Windows-specific functionality for stdio client operations.
"""

import shutil
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO, TextIO, cast

import anyio
from anyio import to_thread
from anyio.abc import Process
from anyio.streams.file import FileReadStream, FileWriteStream
from typing_extensions import deprecated


def get_windows_executable_command(command: str) -> str:
    """
    Get the correct executable command normalized for Windows.

    On Windows, commands might exist with specific extensions (.exe, .cmd, etc.)
    that need to be located for proper execution.

    Args:
        command: Base command (e.g., 'uvx', 'npx')

    Returns:
        str: Windows-appropriate command path
    """
    try:
        # First check if command exists in PATH as-is
        if command_path := shutil.which(command):
            return command_path

        # Check for Windows-specific extensions
        for ext in [".cmd", ".bat", ".exe", ".ps1"]:
            ext_version = f"{command}{ext}"
            if ext_path := shutil.which(ext_version):
                return ext_path

        # For regular commands or if we couldn't find special versions
        return command
    except OSError:
        # Handle file system errors during path resolution
        # (permissions, broken symlinks, etc.)
        return command


class FallbackProcess:
    """
    A fallback process wrapper for Windows to handle async I/O
    when using subprocess.Popen, which provides sync-only FileIO objects.

    This wraps stdin and stdout into async-compatible
    streams (FileReadStream, FileWriteStream),
    so that MCP clients expecting async streams can work properly.
    """

    def __init__(self, popen_obj: subprocess.Popen[bytes]):
        self.popen: subprocess.Popen[bytes] = popen_obj
        self.stdin_raw = popen_obj.stdin  # type: ignore[assignment]
        self.stdout_raw = popen_obj.stdout  # type: ignore[assignment]
        self.stderr = popen_obj.stderr  # type: ignore[assignment]

        self.stdin = FileWriteStream(cast(BinaryIO, self.stdin_raw)) if self.stdin_raw else None
        self.stdout = FileReadStream(cast(BinaryIO, self.stdout_raw)) if self.stdout_raw else None

    async def __aenter__(self):
        """Support async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: BaseException | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        """Terminate and wait on process exit inside a thread."""
        self.popen.terminate()
        await to_thread.run_sync(self.popen.wait)

        # Close the file handles to prevent ResourceWarning
        if self.stdin:
            await self.stdin.aclose()
        if self.stdout:
            await self.stdout.aclose()
        if self.stdin_raw:
            self.stdin_raw.close()
        if self.stdout_raw:
            self.stdout_raw.close()
        if self.stderr:
            self.stderr.close()

    async def wait(self):
        """Async wait for process completion."""
        return await to_thread.run_sync(self.popen.wait)

    def terminate(self):
        """Terminate the subprocess immediately."""
        return self.popen.terminate()

    def kill(self) -> None:
        """Kill the subprocess immediately (alias for terminate)."""
        self.terminate()


# ------------------------
# Updated function
# ------------------------


async def create_windows_process(
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    errlog: TextIO | None = sys.stderr,
    cwd: Path | str | None = None,
) -> Process | FallbackProcess:
    """
    Creates a subprocess in a Windows-compatible way.

    Attempt to use anyio's open_process for async subprocess creation.
    In some cases this will throw NotImplementedError on Windows, e.g.
    when using the SelectorEventLoop which does not support async subprocesses.
    In that case, we fall back to using subprocess.Popen.

    Args:
        command (str): The executable to run
        args (list[str]): List of command line arguments
        env (dict[str, str] | None): Environment variables
        errlog (TextIO | None): Where to send stderr output (defaults to sys.stderr)
        cwd (Path | str | None): Working directory for the subprocess

    Returns:
        FallbackProcess: Async-compatible subprocess with stdin and stdout streams
    """
    try:
        # First try using anyio with Windows-specific flags to hide console window
        process = await anyio.open_process(
            [command, *args],
            env=env,
            # Ensure we don't create console windows for each process
            creationflags=subprocess.CREATE_NO_WINDOW  # type: ignore
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0,
            stderr=errlog,
            cwd=cwd,
        )
        return process
    except NotImplementedError:
        # Windows often doesn't support async subprocess creation, use fallback
        return await _create_windows_fallback_process(command, args, env, errlog, cwd)
    except Exception:
        # Try again without creation flags
        process = await anyio.open_process(
            [command, *args],
            env=env,
            stderr=errlog,
            cwd=cwd,
        )
        return process


async def _create_windows_fallback_process(
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    errlog: TextIO | None = sys.stderr,
    cwd: Path | str | None = None,
) -> FallbackProcess:
    """
    Create a subprocess using subprocess.Popen as a fallback when anyio fails.

    This function wraps the sync subprocess.Popen in an async-compatible interface.
    """
    try:
        # Try launching with creationflags to avoid opening a new console window
        popen_obj = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errlog,
            env=env,
            cwd=cwd,
            bufsize=0,  # Unbuffered output
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return FallbackProcess(popen_obj)

    except Exception:
        # If creationflags failed, fallback without them
        popen_obj = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errlog,
            env=env,
            cwd=cwd,
            bufsize=0,
        )
        return FallbackProcess(popen_obj)


@deprecated(
    "terminate_windows_process is deprecated and will be removed in a future version. "
    "Process termination is now handled internally by the stdio_client context manager."
)
async def terminate_windows_process(process: Process | FallbackProcess):
    """
    Terminate a Windows process.

    Note: On Windows, terminating a process with process.terminate() doesn't
    always guarantee immediate process termination.
    So we give it 2s to exit, or we call process.kill()
    which sends a SIGKILL equivalent signal.

    Args:
        process: The process to terminate
    """
    try:
        process.terminate()
        with anyio.fail_after(2.0):
            await process.wait()
    except TimeoutError:
        # Force kill if it doesn't terminate
        process.kill()
