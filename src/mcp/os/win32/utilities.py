"""Windows-specific functionality for stdio client operations."""

import logging
import shutil
import subprocess
import sys
import weakref
from pathlib import Path
from typing import BinaryIO, TextIO, cast

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

# How often FallbackProcess polls the underlying Popen for exit. Polling keeps the
# wait cancellable: a thread blocked in Popen.wait() cannot be cancelled by anyio,
# which would make every timeout around it ineffective.
_EXIT_POLL_INTERVAL = 0.01

# The Job Object each spawned process was assigned to, so the process tree can be
# terminated through it later.
#
# Values must stay the pywin32 `PyHANDLE` returned by `CreateJobObject`, never a
# detached int: on abandoned-shutdown paths where neither pop site runs, the dying
# weak entry drops the last reference to the `PyHANDLE`, whose destructor closes
# the OS handle — and `KILL_ON_JOB_CLOSE` then reaps the orphaned tree. That
# destructor-close is the only backstop on those paths; storing anything but the
# `PyHANDLE` would turn it into a permanent handle leak.
#
# Keys rely on anyio's `Process` being weakref-able and identity-hashed (it is a
# `dataclass(eq=False)` without `__slots__`); if that ever changes, registration
# fails loudly with a `TypeError` rather than silently. Entries are written once,
# after assignment can no longer fail, and consumed via `pop()` on the event
# loop — no locking needed.
_process_jobs: "weakref.WeakKeyDictionary[Process | FallbackProcess, object]" = weakref.WeakKeyDictionary()


def get_windows_executable_command(command: str) -> str:
    """Get the correct executable command normalized for Windows.

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
    """A fallback process wrapper for Windows to handle async I/O
    when using subprocess.Popen, which provides sync-only FileIO objects.

    This wraps stdin and stdout into async-compatible
    streams (FileReadStream, FileWriteStream),
    so that MCP clients expecting async streams can work properly.
    """

    def __init__(self, popen_obj: subprocess.Popen[bytes]):
        self.popen: subprocess.Popen[bytes] = popen_obj
        stdin = popen_obj.stdin
        stdout = popen_obj.stdout

        self.stdin = FileWriteStream(cast(BinaryIO, stdin)) if stdin else None
        self.stdout = FileReadStream(cast(BinaryIO, stdout)) if stdout else None

    async def wait(self) -> int:
        """Wait for process exit by polling.

        `Popen.wait()` in a worker thread cannot be cancelled by anyio, which would
        defeat every timeout placed around this call; polling keeps it cancellable.
        """
        while (returncode := self.popen.poll()) is None:
            await anyio.sleep(_EXIT_POLL_INTERVAL)
        return returncode

    def terminate(self) -> None:
        """Terminate the subprocess."""
        self.popen.terminate()

    def kill(self) -> None:
        """Kill the subprocess (on Windows this is the same hard kill as terminate)."""
        self.popen.kill()

    @property
    def pid(self) -> int:
        """Return the process ID."""
        return self.popen.pid

    @property
    def returncode(self) -> int | None:
        """Return the exit code, or `None` if the process has not yet terminated.

        Polls the underlying `Popen` so the value updates as soon as the process
        dies, without anyone having to call `wait()`.
        """
        return self.popen.poll()


async def create_windows_process(
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    errlog: TextIO | None = sys.stderr,
    cwd: Path | str | None = None,
) -> Process | FallbackProcess:
    """Creates a subprocess in a Windows-compatible way with Job Object support.

    Attempts to use anyio's open_process for async subprocess creation.
    In some cases this will throw NotImplementedError on Windows, e.g.,
    when using the SelectorEventLoop, which does not support async subprocesses.
    In that case, we fall back to using subprocess.Popen.

    The process is added to a Job Object so that child processes are terminated
    with it. Children the server spawns before the assignment completes — a
    window of two API calls against the server's interpreter cold start — are
    not captured: job membership is inherited at process creation, never
    acquired retroactively.

    Args:
        command (str): The executable to run
        args (list[str]): List of command line arguments
        env (dict[str, str] | None): Environment variables
        errlog (TextIO | None): Where to send stderr output (defaults to sys.stderr)
        cwd (Path | str | None): Working directory for the subprocess

    Returns:
        Process | FallbackProcess: Async-compatible subprocess with stdin and stdout streams
    """
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

    # Created only after a successful spawn: a failed spawn raises before any job
    # exists, so there is no handle to leak on that path. Children the server
    # spawns before AssignProcessToJobObject completes land outside the job
    # (membership is inherited at CreateProcess, never acquired retroactively);
    # the window is two API calls racing the server's interpreter cold start. If
    # it ever bites, the fix is a CREATE_SUSPENDED spawn -> assign -> resume.
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
    """Create a subprocess using subprocess.Popen as a fallback when anyio fails.

    This function wraps the sync subprocess.Popen in an async-compatible interface.
    """
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
        # If creation succeeded but configuration failed, close the handle rather
        # than leaving it to be reclaimed whenever the GC gets to it.
        if job is not None:
            try:
                win32api.CloseHandle(job)
            except pywintypes.error:
                pass
        return None


def _maybe_assign_process_to_job(process: Process | FallbackProcess, job: object | None) -> None:
    """Try to assign a process to a job object.

    On success the job is recorded for the process so that
    `terminate_windows_process_tree` can terminate the whole tree through it.
    If assignment fails for any reason, the job handle is closed.
    """
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
        # Recorded only after the process-handle close above. If that close failed
        # post-assignment, the except below would close the job handle and
        # KILL_ON_JOB_CLOSE would take the just-assigned healthy server with it —
        # accepted, because CloseHandle cannot realistically fail on a handle
        # OpenProcess just returned.
        _process_jobs[process] = job
    except pywintypes.error:
        logger.warning("Failed to assign process %d to Job Object", process.pid, exc_info=True)
        try:
            win32api.CloseHandle(job)
        except pywintypes.error:
            pass


def close_process_job(process: Process | FallbackProcess) -> None:
    """Close the process's Job Object handle, if it still has one.

    The job is created with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, so closing the
    handle also kills any job members that are still alive. Calling this at the end
    of shutdown makes that reaping deterministic — otherwise it would happen whenever
    the handle happens to be garbage-collected. This is a deliberate divergence from
    POSIX, where a well-behaved server's surviving background children are left
    alive. No-op on POSIX and when no job was assigned (or it was already closed by
    tree termination).
    """
    if sys.platform != "win32":
        return

    job = _process_jobs.pop(process, None)
    if job is not None and win32api:
        try:
            win32api.CloseHandle(job)
        except pywintypes.error:
            pass


async def terminate_windows_process_tree(process: Process | FallbackProcess) -> None:
    """Terminate a process and all its children on Windows.

    If the process was assigned to a Job Object at spawn, the job is terminated,
    which kills every process in it immediately. Otherwise only the process itself
    is terminated. Both are immediate hard kills: Windows offers no portable
    equivalent of SIGTERM for a whole tree, so unlike POSIX there is no graceful
    phase here — the stdin-close grace period in the client shutdown is the
    server's opportunity to exit cleanly.
    """
    if sys.platform != "win32":
        return

    job = _process_jobs.pop(process, None)
    if job is not None and win32job:
        try:
            win32job.TerminateJobObject(job, 1)
        except pywintypes.error:
            # Job might already be terminated
            pass
        finally:
            if win32api:
                try:
                    win32api.CloseHandle(job)
                except pywintypes.error:
                    pass

    # Always try to terminate the process itself as well
    try:
        process.terminate()
    except OSError:
        pass
