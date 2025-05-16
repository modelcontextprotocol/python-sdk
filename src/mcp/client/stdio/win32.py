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


async def create_windows_process(
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    errlog: TextIO = sys.stderr,  # For StdioClientTransport._stderr_reader
    cwd: Path | str | None = None,
):
    """
    Creates a subprocess in a Windows-compatible way.
    Ensures stdin, stdout, and stderr are always piped for StdioClientTransport.
    Attempts CREATE_NO_WINDOW, falls back if it fails.
    """

    creation_flags_value = (
        subprocess.CREATE_NO_WINDOW  # type: ignore
        if hasattr(subprocess, "CREATE_NO_WINDOW")
        else 0
    )

    try:
        process = await anyio.open_process(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=cwd,
            creationflags=creation_flags_value,
        )
        return process
    except Exception:
        # Fallback: try to create the process without creation flags
        process = await anyio.open_process(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=cwd,
            creationflags=0,  # Explicitly no special flags in fallback
        )
        return process


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
    except ProcessLookupError:
        # Force kill if it doesn't terminate
        process.kill()
