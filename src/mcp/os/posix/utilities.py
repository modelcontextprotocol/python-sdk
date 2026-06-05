"""POSIX-specific functionality for stdio client operations."""

import logging
import os
import signal
from contextlib import suppress

import anyio
from anyio.abc import Process

logger = logging.getLogger(__name__)

# How often to probe for surviving group members between SIGTERM and SIGKILL.
_GROUP_POLL_INTERVAL = 0.01


async def terminate_posix_process_tree(process: Process, timeout_seconds: float = 2.0) -> None:
    """SIGTERM the process group, wait up to timeout_seconds for it to
    disappear, then SIGKILL whatever remains.

    killpg reaches every descendant atomically, even ones whose parent already
    exited; daemonizers that left the group escape by design. A group only
    disappears once every member is dead and reaped, so a client running as
    PID 1 should reap orphans (e.g. docker run --init) or the wait below runs
    its full timeout.
    """
    # The leader's pid is the pgid (start_new_session). Never use getpgid():
    # it fails once the leader is reaped, even with live members left.
    pgid = process.pid

    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return  # the whole group is already gone
    except PermissionError:
        # EPERM never proves the group is gone (macOS raises it for zombie or
        # foreign-euid members), so keep waiting and escalating.
        logger.warning(
            "No permission to signal some of process group %d; waiting for it to exit anyway", pgid, exc_info=True
        )

    with anyio.move_on_after(timeout_seconds):
        while _group_alive(pgid):
            # Reading returncode reaps the leader on trio; a zombie leader would
            # otherwise keep the group alive for the full timeout.
            _ = process.returncode
            await anyio.sleep(_GROUP_POLL_INTERVAL)
        return

    # ESRCH: died since the last probe. EPERM: we killed what we were allowed to.
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGKILL)


def _group_alive(pgid: int) -> bool:
    """Probe the group with signal 0; only ESRCH proves it is gone."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass  # unsignalable survivors or unreaped zombies; EPERM is ambiguous
    return True
