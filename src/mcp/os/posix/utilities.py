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
    process group and its pgid equals its pid. `os.killpg` on that group reaches
    every descendant in one atomic call — including descendants whose parent (even
    the group leader itself) has already exited, which a walk of the process tree
    would miss.

    Sends SIGTERM to the group, waits up to `timeout_seconds` for the group to
    disappear, then SIGKILLs whatever remains.

    Descendants that move themselves into a new session or process group
    (daemonizers) escape a group kill by design. And a process group only
    disappears once every member is dead *and reaped*: if this client runs as
    PID 1 or a subreaper without reaping orphans, dead descendants reparent to
    it as zombies that keep the group occupied, so the wait below always runs
    to its full timeout. Run such clients under an init shim (e.g.
    `docker run --init`) to get the fast path back.
    """
    # start_new_session=True at spawn makes the leader's pid the pgid; do not ask the
    # OS via getpgid(), which fails with ProcessLookupError once the leader has been
    # reaped even while other group members are still alive.
    pgid = process.pid

    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        # The entire group is already gone; nothing to terminate.
        return
    except PermissionError:
        # What EPERM proves differs by platform. Linux killpg(2): no "permission to
        # send the signal to any of the target processes" — every member was denied,
        # but those members are still alive. macOS kill(2): "when signaling a process
        # group, this error is returned if any members of the group could not be
        # signaled" — one foreign-euid member is enough, and the rest of the group may
        # well have been signalled (current XNU also raises it when only unreaped
        # zombies remain, where Linux would succeed). On no platform does it mean the
        # group is gone, so fall through to the grace wait and SIGKILL escalation —
        # both tolerate EPERM — instead of giving up: members that exit (or get
        # reaped) end the wait early, and permitted members still get the KILL
        # wherever the platform delivers it.
        logger.exception("No permission to signal some of process group %d; waiting for it to exit anyway", pgid)

    with anyio.move_on_after(timeout_seconds):
        while True:
            try:
                # Probe for surviving group members (signal 0 checks without
                # signalling). Only ESRCH proves the group is gone: on Linux the
                # probe keeps succeeding while live members or unreaped zombies
                # remain (so it waits out reaping rather than racing it), and EPERM
                # is ambiguous on every platform.
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return
            except PermissionError:
                # Live members we may not signal (Linux), or a group with foreign
                # members or nothing but zombies (macOS). Keep waiting: reaping
                # turns an all-zombie group into ESRCH above, and unsignalable
                # survivors may still exit on their own within the timeout.
                pass
            # Touching returncode reaps the leader on trio (the property calls
            # Popen.poll()); without it nothing reaps during this loop and the
            # leader's zombie keeps the group alive for the full timeout. On
            # asyncio it is a cheap attribute read. Dead non-leader descendants
            # are reaped by init once orphaned — except under a non-reaping
            # PID-1/subreaper client, where their zombies hold the group here for
            # the full timeout (see docstring).
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
