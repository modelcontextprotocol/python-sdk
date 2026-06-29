"""POSIX-only stdio lifecycle tests: a gracefully-exited server's children survive the client shutdown.

SDK-defined policy, not spec-mandated (docs/migration.md); test_windows.py pins the opposite outcome.
"""

import errno
import sys
from contextlib import suppress

import anyio
import anyio.abc
import pytest

from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.os.win32.utilities import FallbackProcess
from tests.transports.stdio._liveness import (
    accept_alive,
    assert_peer_echoes,
    connect_back_script,
    open_liveness_listener,
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group semantics")


@pytest.mark.anyio
# lax no cover: the per-job 100% coverage gate also runs on Windows, where this file is skipped.
async def test_a_gracefully_exiting_servers_child_survives_the_client_shutdown(  # pragma: lax no cover
    spawned_processes: list[anyio.abc.Process | FallbackProcess],
    terminate_calls: list[anyio.abc.Process | FallbackProcess],
) -> None:
    """Regression: the pre-fix client tree-killed children of a gracefully-exited server."""
    sock, port = await open_liveness_listener()
    async with sock:
        child = connect_back_script(port, echo=True)
        # Server hands its inherited pipes to a child, then exits when stdin closes: the graceful path.
        server = f"import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', {child!r}])\nsys.stdin.read()\n"
        params = StdioServerParameters(command=sys.executable, args=["-c", server])

        # Two interpreter cold starts on a loaded runner; healthy runs take ~0.3s.
        with anyio.fail_after(10.0):
            async with stdio_client(params):
                child_stream = await accept_alive(sock)
            async with child_stream:
                await assert_peer_echoes(child_stream)

    # The echo probe can't tell graceful exit from a kill; the seam can: no escalation, leader exited 0.
    assert terminate_calls == []
    leader = spawned_processes[0]
    assert leader.returncode == 0
    # The child is deliberately left running; the spawned_processes teardown SIGKILLs its group to reap it.


@pytest.mark.anyio
@pytest.mark.usefixtures("spawned_processes")  # failure-path safety net for the parked child
# lax no cover: same Windows-runner coverage-gate reason as above.
async def test_a_surviving_childs_write_to_the_inherited_stdout_fails_with_epipe() -> None:  # pragma: lax no cover
    """Shutdown closes the pipe's only read end deterministically, not at GC time.

    Pins the docs/migration.md claim that a surviving child writing to its
    inherited stdout gets EPIPE once the client is gone. The child parks on its
    socket until `stdio_client` has fully exited (so the write can't race
    transport teardown), then writes to fd 1 and reports the errno back.
    """
    sock, port = await open_liveness_listener()
    async with sock:
        # Pin SIGPIPE to SIG_IGN (CPython's startup default) so the write fails with EPIPE.
        child = (
            f"import os, signal, socket\n"
            f"signal.signal(signal.SIGPIPE, signal.SIG_IGN)\n"
            f"s = socket.create_connection(('127.0.0.1', {port}))\n"
            f"s.sendall(b'alive')\n"
            f"s.recv(4)\n"
            f"try:\n"
            f"    os.write(1, b'x')\n"
            f"    result = b'0'\n"
            f"except OSError as e:\n"
            f"    result = str(e.errno).encode()\n"
            f"s.sendall(result)\n"
        )
        server = f"import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', {child!r}])\nsys.stdin.read()\n"
        params = StdioServerParameters(command=sys.executable, args=["-c", server])

        # Two interpreter cold starts on a loaded runner; healthy runs take ~0.3s.
        with anyio.fail_after(10.0):
            async with stdio_client(params):
                child_stream = await accept_alive(sock)
            async with child_stream:
                # The transport (and the pipe's only read end) is now closed; release the child's write.
                await child_stream.send(b"go")
                # Read to EOF: the child sends its errno report and exits.
                reply = b""
                with suppress(anyio.EndOfStream):
                    while True:
                        reply += await child_stream.receive(16)

    assert int(reply) == errno.EPIPE, f"child reported errno {reply!r}, expected EPIPE"
