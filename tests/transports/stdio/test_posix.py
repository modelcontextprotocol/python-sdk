"""POSIX stdio tests for children of gracefully exited servers.

Unlike Windows, POSIX leaves these children running after client shutdown.
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
    """A server that exits on stdin closure leaves its background child running.

    This SDK policy intentionally differs from Windows.
    """
    sock, port = await open_liveness_listener()
    async with sock:
        child = connect_back_script(port, echo=True)
        server = f"import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', {child!r}])\nsys.stdin.read()\n"
        params = StdioServerParameters(command=sys.executable, args=["-c", server])

        # Allow two cold interpreter starts on loaded CI.
        with anyio.fail_after(10.0):
            async with stdio_client(params):
                child_stream = await accept_alive(sock)
            async with child_stream:
                await assert_peer_echoes(child_stream)

    assert terminate_calls == []
    leader = spawned_processes[0]
    assert leader.returncode == 0
    # The fixture reaps the intentionally surviving child.


@pytest.mark.anyio
@pytest.mark.usefixtures("spawned_processes")  # failure-path safety net for the parked child
# lax no cover: same Windows-runner coverage-gate reason as above.
async def test_a_surviving_childs_write_to_the_inherited_stdout_fails_with_epipe() -> None:  # pragma: lax no cover
    """A surviving child's inherited stdout fails with `EPIPE` after client shutdown.

    The child waits for shutdown, writes to fd 1, then reports errno over its socket.
    """
    sock, port = await open_liveness_listener()
    async with sock:
        # Ignore SIGPIPE so the write reports `EPIPE`.
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

        # Allow two cold interpreter starts on loaded CI.
        with anyio.fail_after(10.0):
            async with stdio_client(params):
                child_stream = await accept_alive(sock)
            async with child_stream:
                await child_stream.send(b"go")
                # Read the complete errno report.
                reply = b""
                with suppress(anyio.EndOfStream):
                    while True:
                        reply += await child_stream.receive(16)

    assert int(reply) == errno.EPIPE, f"child reported errno {reply!r}, expected EPIPE"
