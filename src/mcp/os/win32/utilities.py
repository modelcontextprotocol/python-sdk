"""Windows-specific functionality for stdio client operations."""

import logging
import shutil
import subprocess
import sys
import weakref
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO, TextIO, TypeAlias, cast

import anyio
from anyio.abc import Process
from anyio.streams.file import FileReadStream, FileWriteStream

logger = logging.getLogger(__name__)

# Windows-specific imports for Job Objects
if sys.platform == "win32":
    import pywintypes
    import win32api
    import win32con
    import win32job
else:
    # Type stubs for non-Windows platforms
    win32api = None
    win32con = None
    win32job = None
    pywintypes = None

# How often FallbackProcess polls the underlying Popen for exit.
_EXIT_POLL_INTERVAL = 0.01

# Job Object handle per spawned process, for tree termination at shutdown.
# Values stay pywin32 PyHANDLEs: if no pop site ever runs, the dying weak entry
# drops the last reference and the PyHANDLE destructor closes the handle, which
# is what makes KILL_ON_JOB_CLOSE reap an abandoned tree.
_process_jobs: "weakref.WeakKeyDictionary[Process | FallbackProcess, object]" = weakref.WeakKeyDictionary()


def get_windows_executable_command(command: str) -> str:
    """Resolve the command to a Windows executable path, trying the bare name
    first and then the common script extensions (.cmd, .bat, .exe, .ps1)."""
    try:
        if command_path := shutil.which(command):
            return command_path

        for ext in [".cmd", ".bat", ".exe", ".ps1"]:
            ext_version = f"{command}{ext}"
            if ext_path := shutil.which(ext_version):
                return ext_path

        return command
    except OSError:
        return command  # path probing failed (permissions, broken symlinks)


class FallbackProcess:
    """Async wrapper around subprocess.Popen for Windows event loops without
    async subprocess support (SelectorEventLoop)."""

    def __init__(self, popen_obj: subprocess.Popen[bytes]) -> None:
        self.popen: subprocess.Popen[bytes] = popen_obj
        stdin = popen_obj.stdin
        stdout = popen_obj.stdout

        self.stdin = FileWriteStream(cast(BinaryIO, stdin)) if stdin else None
        self.stdout = FileReadStream(cast(BinaryIO, stdout)) if stdout else None

    async def wait(self) -> int:
        """Wait for exit by polling; a thread blocked in Popen.wait() cannot be
        cancelled by anyio, which would defeat every timeout around this call."""
        while (returncode := self.popen.poll()) is None:
            await anyio.sleep(_EXIT_POLL_INTERVAL)
        return returncode

    def terminate(self) -> None:
        """Terminate the subprocess."""
        self.popen.terminate()

    def kill(self) -> None:
        """Kill the subprocess (same hard kill as terminate on Windows)."""
        self.popen.kill()

    @property
    def pid(self) -> int:
        """Return the process ID."""
        return self.popen.pid

    @property
    def returncode(self) -> int | None:
        """Exit code, or None while running; polls Popen so death is observable
        without anyone calling wait()."""
        return self.popen.poll()


# The process handle stdio_client drives: anyio's Process, or the Popen-backed
# fallback used on Windows event loops without async subprocess support.
ServerProcess: TypeAlias = Process | FallbackProcess


async def create_windows_process(
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    errlog: TextIO | None = sys.stderr,
    cwd: Path | str | None = None,
) -> Process | FallbackProcess:
    """Spawn the server inside a Job Object so its children can be terminated
    with it; falls back to subprocess.Popen on event loops without async
    subprocess support."""
    try:
        process = await anyio.open_process(
            [command, *args],
            env=env,
            # Ensure we don't create console windows for each process
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stderr=errlog,
            cwd=cwd,
        )
    except NotImplementedError:
        # Windows event loops without async subprocess support (SelectorEventLoop)
        process = await _create_windows_fallback_process(command, args, env, errlog, cwd)

    # Children spawned before the assignment completes land outside the job
    # (membership is inherited at CreateProcess, never acquired retroactively);
    # if that ever bites, the fix is a CREATE_SUSPENDED spawn -> assign -> resume.
    job = _create_job_object()
    _maybe_assign_process_to_job(process, job)
    return process


async def _create_windows_fallback_process(
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    errlog: TextIO | None = sys.stderr,
    cwd: Path | str | None = None,
) -> FallbackProcess:
    """Spawn via subprocess.Popen and wrap it in FallbackProcess."""
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


def _create_job_object() -> object | None:
    """Create a Windows Job Object configured to terminate all processes when closed."""
    if sys.platform != "win32" or not win32api or not win32job:
        return None

    job = None
    try:
        job = win32job.CreateJobObject(None, "")
        extended_info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)

        extended_info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, extended_info)
        return job
    except pywintypes.error:
        logger.warning("Failed to create Job Object for process tree management", exc_info=True)
        # If creation succeeded but configuration failed, close the handle now.
        if job is not None:
            _close_job_handle(job)
        return None


def _maybe_assign_process_to_job(process: Process | FallbackProcess, job: object | None) -> None:
    """Assign the process to the job and record it for tree termination; on
    any failure the job handle is closed instead."""
    if job is None:
        return

    if sys.platform != "win32" or not win32api or not win32con or not win32job:
        return

    try:
        process_handle = win32api.OpenProcess(
            win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, process.pid
        )
        if not process_handle:
            raise pywintypes.error(0, "OpenProcess", "Failed to open process handle")

        try:
            win32job.AssignProcessToJobObject(job, process_handle)
        finally:
            win32api.CloseHandle(process_handle)
        # Record only after the CloseHandle above succeeded: had it failed, the
        # except below would close the job and KILL_ON_JOB_CLOSE takes the server.
        _process_jobs[process] = job
    except pywintypes.error:
        logger.warning("Failed to assign process %d to Job Object", process.pid, exc_info=True)
        _close_job_handle(job)


def close_process_job(process: Process | FallbackProcess) -> None:
    """Close the process's Job Object handle, killing any members still alive
    (KILL_ON_JOB_CLOSE) deterministically rather than at GC time; a deliberate
    divergence from POSIX, where a graceful server's children are left alive."""
    if sys.platform != "win32":
        return

    job = _process_jobs.pop(process, None)
    if job is not None:
        _close_job_handle(job)


async def terminate_windows_process_tree(process: Process | FallbackProcess) -> None:
    """Terminate the job (an immediate hard kill of every member), or just the
    process if it has no job. Windows has no tree-wide SIGTERM; the stdin-close
    grace period is the server's chance to exit cleanly."""
    if sys.platform != "win32":
        return

    job = _process_jobs.pop(process, None)
    if job is not None and win32job:
        try:
            with suppress(pywintypes.error):  # the job might already be terminated
                win32job.TerminateJobObject(job, 1)
        finally:
            _close_job_handle(job)

    # The process may have no job (creation or assignment failed); kill it directly too.
    try:
        process.terminate()
    except OSError:
        pass


def _close_job_handle(job: object) -> None:
    """Close a Job Object handle, tolerating one that is already closed."""
    if win32api and pywintypes:
        with suppress(pywintypes.error):
            win32api.CloseHandle(job)
