"""POSIX-only stdio lifecycle tests: what happens to a well-behaved server's
background children when the client shuts down.

The policy under test is SDK-defined, not spec-mandated (docs/migration.md,
"`stdio_client` no longer kills children of a gracefully-exited server on
POSIX"): a server that exits on its own after stdin closes keeps its surviving
children — their lifetime is the server's business. The same scenario on
Windows has the opposite documented outcome (the Job Object reaps survivors at
shutdown); see tests/transports/stdio/test_windows.py.
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
# Excluded from coverage (lax: exempt from strict-no-cover) because coverage is enforced
# per CI job at 100%, including on Windows runners, where this file is skipped.
async def test_a_gracefully_exiting_servers_child_survives_the_client_shutdown(  # pragma: lax no cover
    spawned_processes: list[anyio.abc.Process | FallbackProcess],
    terminate_calls: list[anyio.abc.Process | FallbackProcess],
) -> None:
    """A server that exits on stdin closure keeps its background child: the client
    never escalates, and the child is still running after `stdio_client` returns.

    SDK-defined policy pinned per docs/migration.md; the pre-fix client misread the
    child's inherited pipes as the server hanging and tree-killed it. The Windows
    twin in test_windows.py pins the opposite documented outcome.
    """
    sock, port = await open_liveness_listener()
    async with sock:
        child = connect_back_script(port, echo=True)
        # The server hands its inherited pipes to a child, then exits as soon as
        # its stdin closes — the well-behaved graceful path.
        server = f"import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', {child!r}])\nsys.stdin.read()\n"
        params = StdioServerParameters(command=sys.executable, args=["-c", server])

        # Two interpreter cold starts on a loaded runner; healthy runs take ~0.3s.
        with anyio.fail_after(10.0):
            async with stdio_client(params):
                child_stream = await accept_alive(sock)
            async with child_stream:
                # Only a live process answers an echo: the child survived shutdown.
                await assert_peer_echoes(child_stream)

    # A FIN-shaped probe could not tell graceful exit from a kill; the seam can:
    # the escalation was never invoked, and the leader exited 0 on stdin closure.
    assert terminate_calls == []
    leader = spawned_processes[0]
    assert leader.returncode == 0
    # The child is deliberately left running; the spawned_processes teardown
    # SIGKILLs the spawn-time process group to reap it.


@pytest.mark.anyio
@pytest.mark.usefixtures("spawned_processes")  # failure-path safety net for the parked child
# Excluded from coverage for the same Windows-runner reason as above.
async def test_a_surviving_childs_write_to_the_inherited_stdout_fails_with_epipe() -> None:  # pragma: lax no cover
    """Once the client is gone, a surviving child writing to the stdout pipe it
    inherited from the server gets EPIPE: the pipe's only read end was the
    client's, and shutdown closed it deterministically rather than at GC time.

    Pins the docs/migration.md claim "a surviving child that keeps writing to an
    inherited stdout receives EPIPE/SIGPIPE once the client is gone" (SDK-defined;
    documented but previously unproven).

    Steps:
    1. The server hands its stdio pipes to a child and exits on stdin closure.
    2. The child parks on its socket until the test signals that `stdio_client`
       has fully exited, so the write cannot race the transport teardown.
    3. The child writes one byte to its inherited fd 1 and reports the errno
       (0 on success) back over the socket.
    """
    sock, port = await open_liveness_listener()
    async with sock:
        # The child pins SIGPIPE to SIG_IGN explicitly (CPython already starts
        # that way) so the write observably fails with EPIPE instead of the test
        # depending on interpreter startup details for the child's survival.
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
                # The context has fully exited: the transport, and with it the
                # pipe's only read end, is closed. Release the child's write.
                await child_stream.send(b"go")
                # The child sends its errno report and exits, so read to EOF: the
                # complete reply is everything before the kernel's FIN.
                reply = b""
                with suppress(anyio.EndOfStream):
                    while True:
                        reply += await child_stream.receive(16)

    assert int(reply) == errno.EPIPE, f"child reported errno {reply!r}, expected EPIPE"
