"""POSIX-specific functionality for stdio client operations."""

import logging
import os
import signal
from contextlib import suppress

import anyio
from anyio.abc import Process

logger = logging.getLogger(__name__)

# How often to probe for surviving process-group members between SIGTERM and SIGKILL.
_GROUP_POLL_INTERVAL = 0.01


async def terminate_posix_process_tree(process: Process, timeout_seconds: float = 2.0) -> None:
    """Terminate a process and all its descendants on POSIX systems.

    The process was spawned with `start_new_session=True`, so it leads its own
    process group and `os.killpg` reaches every descendant in one atomic call,
    even those whose parent (including the leader itself) has already exited.
    Sends SIGTERM to the group, waits up to `timeout_seconds` for the group to
    disappear, then SIGKILLs whatever remains.

    Descendants that move themselves into a new session or process group
    (daemonizers) escape a group kill by design. A group only disappears once
    every member is dead *and reaped*: a client running as PID 1 without reaping
    orphans keeps zombie descendants in the group and makes the wait below run
    its full timeout (run such clients under an init shim, e.g. `docker run
    --init`).
    """
    # start_new_session=True makes the leader's pid the pgid. Never ask via
    # getpgid(): it fails once the leader is reaped, even with live members left.
    pgid = process.pid

    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return  # the entire group is already gone
    except PermissionError:
        # EPERM never proves the group is gone (Linux: every member denied but
        # alive; macOS: one foreign-euid or zombie member is enough, the rest
        # were signalled), so keep waiting and escalating — both tolerate it.
        logger.warning(
            "No permission to signal some of process group %d; waiting for it to exit anyway", pgid, exc_info=True
        )

    with anyio.move_on_after(timeout_seconds):
        while _group_alive(pgid):
            # Reading `returncode` reaps the leader on trio (the property calls
            # Popen.poll()); without it the leader's zombie would keep the group
            # alive for the full timeout. On asyncio it is a cheap attribute read.
            _ = process.returncode
            await anyio.sleep(_GROUP_POLL_INTERVAL)
        return

    with suppress(ProcessLookupError, PermissionError):
        # ESRCH: the group died between the last probe and now. EPERM: whatever
        # the platform let us signal has been KILLed; the rest is not ours to touch.
        os.killpg(pgid, signal.SIGKILL)


def _group_alive(pgid: int) -> bool:
    """Probe the group with signal 0. Only ESRCH proves it is gone: the probe
    keeps succeeding while live members or unreaped zombies remain, and EPERM
    is ambiguous on every platform."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Unsignalable survivors or zombies; keep waiting — reaping turns an
        # all-zombie group into ESRCH, and survivors may yet exit on their own.
        pass
    return True
