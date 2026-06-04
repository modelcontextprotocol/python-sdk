"""Fixtures for the stdio lifecycle suite: recording seams around the spawn and
tree-termination internals of `stdio_client` (the real implementations still run),
plus the failure-path safety net that keeps a crashed test from orphaning its
sleep-forever subprocesses.
"""

import os
import signal
import sys
from collections.abc import Generator
from contextlib import suppress
from pathlib import Path
from typing import TextIO

import anyio.abc
import pytest

from mcp.client import stdio
from mcp.client.stdio import _create_platform_compatible_process, _terminate_process_tree
from mcp.os.win32.utilities import FallbackProcess


@pytest.fixture
def spawned_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[list[anyio.abc.Process | FallbackProcess]]:
    """Record every process `stdio_client` spawns; the real spawn still runs.

    Tests inspect the recorded processes afterwards (exit codes, concrete type on
    the Windows fallback path). Teardown SIGKILLs each spawn-time process group on
    POSIX, in both of its roles: failure-path safety net (a test that dies mid-body
    cannot orphan its sleep-forever descendants for an hour) and the reaper for
    tests that deliberately leave a survivor running, like the POSIX survival
    test's echo child. On Windows there is no process group to signal (the Job
    Object covers strays).
    """
    spawned: list[anyio.abc.Process | FallbackProcess] = []

    async def recording_spawn(
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
        errlog: TextIO = sys.stderr,
        cwd: Path | str | None = None,
    ) -> anyio.abc.Process | FallbackProcess:
        process = await _create_platform_compatible_process(command, args, env, errlog, cwd)
        spawned.append(process)
        return process

    monkeypatch.setattr(stdio, "_create_platform_compatible_process", recording_spawn)
    yield spawned
    _kill_spawn_groups(spawned)


@pytest.fixture
def terminate_calls(monkeypatch: pytest.MonkeyPatch) -> list[anyio.abc.Process | FallbackProcess]:
    """Record every invocation of `stdio_client`'s tree-termination seam; the real
    termination still runs.

    An empty list after the context exits proves the graceful path: the server was
    never escalated against, which a socket signal alone cannot establish (a FIN
    looks the same whether the peer exited on stdin closure or was killed).
    """
    terminated: list[anyio.abc.Process | FallbackProcess] = []

    async def recording_terminate(process: anyio.abc.Process | FallbackProcess) -> None:
        terminated.append(process)
        await _terminate_process_tree(process)

    monkeypatch.setattr(stdio, "_terminate_process_tree", recording_terminate)
    return terminated


# Excluded from coverage (lax: exempt from strict-no-cover): registered on every
# platform but a no-op on Windows, whose runners enforce 100% coverage per job.
def _kill_spawn_groups(spawned: list[anyio.abc.Process | FallbackProcess]) -> None:  # pragma: lax no cover
    """SIGKILL each spawn-time process group; see `spawned_processes`."""
    if sys.platform == "win32":
        return
    for process in spawned:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
