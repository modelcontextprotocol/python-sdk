"""Real-subprocess stdio lifecycle tests that hold on both POSIX and Windows.

The `stdio_client` tests each launch a real server through the public API and pin
one lifecycle behaviour, with kernel-level liveness sockets as the only
synchronization; the `FallbackProcess` tests wrap a raw `subprocess.Popen`
directly. Platform-divergent shutdown policy lives in test_posix.py /
test_windows.py; the full protocol round trip is pinned by
tests/interaction/transports/test_stdio.py and in-process shutdown logic by
tests/client/test_stdio.py.
"""

import os
import subprocess
import sys
import threading
from contextlib import AsyncExitStack
from pathlib import Path

import anyio
import anyio.abc
import pytest

from mcp.client import stdio
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.os.win32.utilities import FallbackProcess
from tests.transports.stdio._liveness import (
    accept_alive,
    assert_stream_closed,
    connect_back_script,
    open_liveness_listener,
)


@pytest.mark.anyio
async def test_a_server_that_exits_on_stdin_close_is_reaped_and_never_terminated(
    spawned_processes: list[anyio.abc.Process | FallbackProcess],
    terminate_calls: list[anyio.abc.Process | FallbackProcess],
) -> None:
    """The happy path: closing stdin alone shuts a well-behaved server down -- it
    exits with code 0 and the escalation seam is never invoked."""
    async with AsyncExitStack() as stack:
        sock, port = await open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        # The server exits on its own at stdin EOF -- the well-behaved response
        # to shutdown's first step.
        server = (
            f"import socket, sys\n"
            f"s = socket.create_connection(('127.0.0.1', {port}))\n"
            f"s.sendall(b'alive')\n"
            f"sys.stdin.read()\n"
        )
        params = StdioServerParameters(command=sys.executable, args=["-c", server])

        # The bound covers one interpreter cold start on a loaded runner; a healthy
        # run takes well under a second.
        with anyio.fail_after(10.0):
            async with stdio_client(params):
                stream = await accept_alive(sock)
                stack.push_async_callback(stream.aclose)

        await assert_stream_closed(stream)

    assert spawned_processes[0].returncode == 0
    assert terminate_calls == []


@pytest.mark.anyio
async def test_cancelling_the_client_mid_session_terminates_the_whole_server_tree(
    monkeypatch: pytest.MonkeyPatch,
    spawned_processes: list[anyio.abc.Process | FallbackProcess],
    terminate_calls: list[anyio.abc.Process | FallbackProcess],
) -> None:
    """Cancellation (a client timeout, app shutdown) still runs the full shutdown
    against a real process tree: a server that ignores stdin closure is escalated
    against, and its child dies with it."""
    monkeypatch.setattr(stdio, "PROCESS_TERMINATION_TIMEOUT", 0.2)

    async with AsyncExitStack() as stack:
        sock, port = await open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        child = connect_back_script(port)
        # The parent never reads stdin and blocks forever, so only the escalation
        # can end it -- which cancellation must not skip.
        parent = f"import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', {child!r}])\n" + connect_back_script(
            port
        )
        params = StdioServerParameters(command=sys.executable, args=["-c", parent])

        entered = anyio.Event()
        # Cancel a scope owned by the client's task, not the test's task group: a
        # host self-cancel is delivered by throwing through this test function's
        # suspended frames, and Python 3.11's tracer loses coverage events after
        # such a throw() traversal (python/cpython#106749).
        cancel_scope = anyio.CancelScope()

        async def run_client_until_cancelled() -> None:
            with cancel_scope:
                async with stdio_client(params):
                    entered.set()
                    await anyio.sleep_forever()

        streams: list[anyio.abc.SocketStream] = []
        # The bound covers two interpreter cold starts on a loaded runner plus the
        # shortened escalation wait; a healthy run takes around a second.
        with anyio.fail_after(10.0):
            async with anyio.create_task_group() as tg:
                tg.start_soon(run_client_until_cancelled)
                await entered.wait()
                for _ in range(2):
                    stream = await accept_alive(sock)
                    stack.push_async_callback(stream.aclose)
                    streams.append(stream)
                cancel_scope.cancel()

        for stream in streams:
            await assert_stream_closed(stream)

    assert terminate_calls == spawned_processes


@pytest.mark.anyio
async def test_a_server_that_exits_mid_session_keeps_its_own_exit_code(
    spawned_processes: list[anyio.abc.Process | FallbackProcess],
    terminate_calls: list[anyio.abc.Process | FallbackProcess],
) -> None:
    """A server that dies on its own mid-session is reaped with the exit code it
    chose: the client surfaces the child's true status rather than synthesizing
    one, and the escalation seam confirms nothing was terminated along the way."""
    async with AsyncExitStack() as stack:
        sock, port = await open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        server = (
            f"import socket, sys\n"
            f"s = socket.create_connection(('127.0.0.1', {port}))\n"
            f"s.sendall(b'alive')\n"
            f"sys.exit(7)\n"
        )
        params = StdioServerParameters(command=sys.executable, args=["-c", server])

        # The bound covers one interpreter cold start on a loaded runner; a healthy
        # run takes well under a second.
        with anyio.fail_after(10.0):
            # no branch: coverage mis-traces the exit arcs of a nested `async with` on 3.11+.
            async with stdio_client(params):  # pragma: no branch
                stream = await accept_alive(sock)
                stack.push_async_callback(stream.aclose)
                # The server is already gone before shutdown begins.
                await assert_stream_closed(stream)

    assert spawned_processes[0].returncode == 7
    assert terminate_calls == []


@pytest.mark.anyio
async def test_server_stderr_output_reaches_the_errlog_file(
    tmp_path: Path,
    spawned_processes: list[anyio.abc.Process | FallbackProcess],
) -> None:
    """What the server writes to stderr lands in the file passed as `errlog`. The
    spawn hands over errlog's file descriptor as the child's stderr, so it must be
    a real file -- an in-memory StringIO has no fileno."""
    marker = "stdio-lifecycle stderr marker 4242"

    async with AsyncExitStack() as stack:
        sock, port = await open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        server = (
            f"import socket, sys\n"
            f"s = socket.create_connection(('127.0.0.1', {port}))\n"
            f"s.sendall(b'alive')\n"
            f"sys.stderr.write({marker!r} + '\\n')\n"
            f"sys.stderr.flush()\n"
            f"sys.stdin.read()\n"
        )
        params = StdioServerParameters(command=sys.executable, args=["-c", server])

        with (tmp_path / "errlog.txt").open("w+", encoding="utf-8") as errlog:
            # The bound covers one interpreter cold start on a loaded runner; a
            # healthy run takes well under a second.
            with anyio.fail_after(10.0):
                async with stdio_client(params, errlog=errlog):
                    stream = await accept_alive(sock)
                    stack.push_async_callback(stream.aclose)

            # The server exited on stdin EOF, so every stderr write it made has
            # reached the file descriptor.
            errlog.seek(0)
            content = errlog.read()

    assert marker in content
    assert spawned_processes[0].returncode == 0


@pytest.mark.skipif(
    not hasattr(os, "waitid"), reason="needs os.waitid(WNOWAIT); absent on Windows and macOS before 3.13"
)
# lax no cover: Windows runners enforce 100% per job but lack os.waitid and skip this
# test; test_windows.py's SelectorEventLoop lifecycle test exercises the property there.
def test_fallback_process_reports_death_through_returncode_without_a_wait_call() -> None:  # pragma: lax no cover
    """`FallbackProcess.returncode` observes process death on its own -- pre-fix it
    returned Popen's cached value, which stays None until someone calls wait()/poll().

    `os.waitid(WEXITED | WNOWAIT)` waits for the child to become reapable without
    reaping it or priming Popen's cache (which would mask the regression); the
    pre-fix cached read would still see None here. stdout EOF is NOT such a signal:
    the kernel closes the pipes before the exit status is published, so an
    EOF-then-assert version flakes.
    """
    popen = subprocess.Popen(
        [sys.executable, "-c", "pass"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert popen.stdin is not None and popen.stdout is not None
    try:
        process = FallbackProcess(popen)

        os.waitid(os.P_PID, popen.pid, os.WEXITED | os.WNOWAIT)
        assert process.returncode == 0
    finally:
        popen.stdin.close()
        popen.stdout.close()
        # The WNOWAIT above left the child unreaped; reap it so no zombie (and no
        # Popen ResourceWarning) outlives the test.
        popen.wait()


@pytest.mark.anyio
async def test_fallback_process_wait_is_cancellable_while_the_child_lives() -> None:
    """`FallbackProcess.wait()` honours cancellation while the child is still
    running -- pre-fix it parked `Popen.wait()` in a worker thread anyio will not
    abandon, which blocks every cancellation aimed at it. Runs everywhere: the
    wrapper holds a plain Popen."""
    popen = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert popen.stdin is not None and popen.stdout is not None
    # Pre-fix, no timeout below can fire while the worker thread is parked in
    # Popen.wait(); killing the child turns that regression's hang into a clean failure.
    watchdog = threading.Timer(8.0, popen.kill)
    watchdog.start()
    try:
        process = FallbackProcess(popen)

        # move_on_after's short deadline is the time-based feature under test --
        # cancellability -- not a wait for an async condition.
        with anyio.fail_after(5):
            with anyio.move_on_after(0.1) as scope:
                await process.wait()

        assert scope.cancelled_caught
        # Only the wait was cancelled; the child itself is untouched.
        assert popen.poll() is None
    finally:
        watchdog.cancel()
        popen.kill()
        popen.wait()
        popen.stdin.close()
        popen.stdout.close()
