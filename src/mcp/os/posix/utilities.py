"""
POSIX-specific functionality for stdio client operations.
"""

import logging
import os
import signal

import anyio
from anyio.abc import Process

logger = logging.getLogger(__name__)


async def terminate_posix_process_tree(process: Process, timeout_seconds: float = 2.0) -> None:
    """
    Terminate a process and all its children on POSIX systems.

    Uses os.killpg() for atomic process group termination.

    Args:
        process: The process to terminate
        timeout_seconds: Timeout in seconds before force killing (default: 2.0)
    """
    pid = getattr(process, "pid", None) or getattr(getattr(process, "popen", None), "pid", None)
    if not pid:  # pragma: no cover
        # No PID means there's no process to terminate - it either never started,
        # already exited, or we have an invalid process object
        return

    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)

        with anyio.move_on_after(timeout_seconds):
            while True:
                try:
                    # Check if process group still exists (signal 0 = check only)
                    os.killpg(pgid, 0)
                    await anyio.sleep(0.1)
                except ProcessLookupError:
                    return

        try:  # pragma: no cover
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:  # pragma: no cover
            pass

    except (ProcessLookupError, PermissionError, OSError) as e:  # pragma: no cover
        logger.warning(
            f"Process group termination failed for PID {pid}: {e}, falling back to simple terminate"
        )  # pragma: no cover
        try:  # pragma: no cover
            process.terminate()  # pragma: no cover
            with anyio.fail_after(timeout_seconds):  # pragma: no cover
                await process.wait()  # pragma: no cover
        except Exception:  # pragma: no cover
            logger.warning(f"Process termination failed for PID {pid}, attempting force kill")  # pragma: no cover
            try:  # pragma: no cover
                process.kill()  # pragma: no cover
            except Exception:  # pragma: no cover
                logger.exception(f"Failed to kill process {pid}")  # pragma: no cover
