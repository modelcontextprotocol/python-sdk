"""POSIX-specific functionality for stdio client operations."""

import logging
import os
import signal

import anyio
from anyio.abc import Process

logger = logging.getLogger(__name__)

# How often to probe for surviving process-group members between SIGTERM and SIGKILL.
_GROUP_POLL_INTERVAL = 0.01


async def terminate_posix_process_tree(process: Process, timeout_seconds: float = 2.0) -> None:
    """Terminate a process and all its descendants on POSIX systems.

    The process was spawned with `start_new_session=True`, so it leads its own
    process group and `os.killpg` reaches every descendant in one atomic call,
    including those whose parent (even the leader itself) has already exited.
    Sends SIGTERM to the group, waits up to `timeout_seconds` for the group to
    disappear, then SIGKILLs whatever remains.

    Descendants that move themselves into a new session or process group
    (daemonizers) escape a group kill by design. A group only disappears once
    every member is dead and reaped: a client running as PID 1 or a subreaper
    without reaping orphans keeps zombie descendants in the group and makes the
    wait below run its full timeout (run such clients under an init shim, e.g.
    `docker run --init`).
    """
    # start_new_session=True makes the leader's pid the pgid. Never ask via
    # getpgid(): it fails once the leader is reaped, even with live members left.
    pgid = process.pid

    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        # The entire group is already gone; nothing to terminate.
        return
    except PermissionError:
        # What EPERM proves differs by platform. Linux killpg(2): every member was
        # denied, but all are still alive. macOS kill(2): one foreign-euid member is
        # enough, and the rest may well have been signalled (current XNU also raises
        # it for all-zombie groups, where Linux succeeds). On no platform does it
        # mean the group is gone, so fall through to the grace wait and SIGKILL
        # escalation (both tolerate EPERM) instead of giving up. A warning rather
        # than an error: on macOS this can simply mean the group already exited
        # cleanly and is waiting to be reaped.
        logger.warning(
            "No permission to signal some of process group %d; waiting for it to exit anyway", pgid, exc_info=True
        )

    with anyio.move_on_after(timeout_seconds):
        while True:
            try:
                # Probe with signal 0. Only ESRCH proves the group is gone: the
                # probe keeps succeeding while live members or unreaped zombies
                # remain, and EPERM is ambiguous on every platform.
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return
            except PermissionError:
                # Unsignalable survivors (or, on macOS, zombies/foreign members).
                # Keep waiting: reaping turns an all-zombie group into ESRCH above,
                # and survivors may still exit on their own within the timeout.
                pass
            # Deliberate: touching returncode reaps the leader on trio (the property
            # calls Popen.poll()); without it the leader's zombie keeps the group
            # alive for the full timeout. On asyncio it is a cheap attribute read.
            _ = process.returncode
            await anyio.sleep(_GROUP_POLL_INTERVAL)

    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        # The group died between the last probe and the kill.
        pass
    except PermissionError:
        # Same per-platform ambiguity as the SIGTERM above: whatever the platform
        # let us signal has now been KILLed; the rest is not ours to touch.
        pass
