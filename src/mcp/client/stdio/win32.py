"""
Windows-specific functionality for stdio client operations.
"""

import shutil
import subprocess
import sys
from pathlib import Path
from typing import TextIO

import anyio
from anyio.abc import Process
from anyio.streams.file import FileReadStream, FileWriteStream

from typing import Optional, TextIO, Union
from pathlib import Path


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

class DummyProcess:
    """
    A fallback process wrapper for Windows to handle async I/O 
    when using subprocess.Popen, which provides sync-only FileIO objects.
    
    This wraps stdin and stdout into async-compatible streams (FileReadStream, FileWriteStream),
    so that MCP clients expecting async streams can work properly.
    """
    def __init__(self, popen_obj: subprocess.Popen):
        self.popen = popen_obj
        self.stdin_raw = popen_obj.stdin
        self.stdout_raw = popen_obj.stdout
        self.stderr = popen_obj.stderr

        # Wrap into async-compatible AnyIO streams
        self.stdin = FileWriteStream(self.stdin_raw)
        self.stdout = FileReadStream(self.stdout_raw)

    async def __aenter__(self):
        """Support async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Terminate and wait on process exit inside a thread."""
        self.popen.terminate()
        await anyio.to_thread.run_sync(self.popen.wait)

    async def wait(self):
        """Async wait for process completion."""
        return await anyio.to_thread.run_sync(self.popen.wait)

    def terminate(self):
        """Terminate the subprocess immediately."""
        return self.popen.terminate()

# ------------------------
# Updated function
# ------------------------

async def create_windows_process(
    command: str,
    args: list[str],
    env: Optional[dict[str, str]] = None,
    errlog: Optional[TextIO] = sys.stderr,
    cwd: Union[Path, str, None] = None,
):
    """
    Creates a subprocess in a Windows-compatible way.
    
    On Windows, asyncio.create_subprocess_exec has incomplete support 
    (NotImplementedError when trying to open subprocesses). 
    Therefore, we fallback to subprocess.Popen and wrap it for async usage.

    Args:
        command (str): The executable to run
        args (list[str]): List of command line arguments
        env (dict[str, str] | None): Environment variables
        errlog (TextIO | None): Where to send stderr output (defaults to sys.stderr)
        cwd (Path | str | None): Working directory for the subprocess

    Returns:
        DummyProcess: Async-compatible subprocess with stdin and stdout streams
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
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return DummyProcess(popen_obj)

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
        return DummyProcess(popen_obj)

async def terminate_windows_process(process: Process):
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
