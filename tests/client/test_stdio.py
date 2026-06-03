import errno
import shutil
import sys
import time
from contextlib import AsyncExitStack, suppress

import anyio
import anyio.abc
import pytest

from mcp.client.session import ClientSession
from mcp.client.stdio import (
    PROCESS_TERMINATION_TIMEOUT,
    StdioServerParameters,
    _create_platform_compatible_process,
    _terminate_process_tree,
    stdio_client,
)
from mcp.os.win32.utilities import FallbackProcess
from mcp.shared.exceptions import MCPError
from mcp.shared.message import SessionMessage
from mcp.types import CONNECTION_CLOSED, JSONRPCMessage, JSONRPCRequest, JSONRPCResponse

tee = shutil.which("tee")


@pytest.mark.anyio
@pytest.mark.skipif(tee is None, reason="could not find tee command")
async def test_stdio_context_manager_exiting():
    assert tee is not None
    async with stdio_client(StdioServerParameters(command=tee)) as (_, _):
        pass


@pytest.mark.anyio
@pytest.mark.skipif(tee is None, reason="could not find tee command")
async def test_stdio_client():
    assert tee is not None
    server_parameters = StdioServerParameters(command=tee)

    async with stdio_client(server_parameters) as (read_stream, write_stream):
        # Test sending and receiving messages
        messages = [
            JSONRPCRequest(jsonrpc="2.0", id=1, method="ping"),
            JSONRPCResponse(jsonrpc="2.0", id=2, result={}),
        ]

        async with write_stream:
            for message in messages:
                session_message = SessionMessage(message)
                await write_stream.send(session_message)

        read_messages: list[JSONRPCMessage] = []
        async with read_stream:
            async for message in read_stream:
                if isinstance(message, Exception):  # pragma: no cover
                    raise message

                read_messages.append(message.message)
                if len(read_messages) == 2:
                    break

        assert len(read_messages) == 2
        assert read_messages[0] == JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
        assert read_messages[1] == JSONRPCResponse(jsonrpc="2.0", id=2, result={})


@pytest.mark.anyio
async def test_stdio_client_bad_path():
    """Check that the connection doesn't hang if process errors."""
    server_params = StdioServerParameters(command=sys.executable, args=["-c", "non-existent-file.py"])
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # The session should raise an error when the connection closes
            with pytest.raises(MCPError) as exc_info:
                await session.initialize()

            # Check that we got a connection closed error
            assert exc_info.value.error.code == CONNECTION_CLOSED
            assert "Connection closed" in exc_info.value.error.message


@pytest.mark.anyio
async def test_stdio_client_nonexistent_command():
    """Test that stdio_client raises an error for non-existent commands."""
    # Create a server with a non-existent command
    server_params = StdioServerParameters(
        command="/path/to/nonexistent/command",
        args=["--help"],
    )

    # Should raise an error when trying to start the process
    with pytest.raises(OSError) as exc_info:
        async with stdio_client(server_params) as (_, _):
            pass  # pragma: no cover

    # The error should indicate the command was not found (ENOENT: No such file or directory)
    assert exc_info.value.errno == errno.ENOENT


# ---------------------------------------------------------------------------
# Socket-based deterministic child liveness probe
# ---------------------------------------------------------------------------
#
# The cleanup tests below verify that exiting `stdio_client` (or calling
# `_terminate_process_tree()` directly) kills the spawned process — including
# its *entire* process tree, which is critical for cleaning up tools like
# `npx` that spawn their own subprocesses.
#
# Mechanism: each subprocess connects a TCP socket back to a listener owned by
# the test. We then use two kernel-guaranteed blocking-I/O signals — neither
# requires any `sleep()` or polling loop:
#
#   1. `await listener.accept()` blocks until the subprocess connects,
#      proving it is running (and that any setup lines preceding the connect
#      in its script, such as installing a signal handler, have executed).
#   2. After cleanup, `await stream.receive(1)` raises `EndOfStream` (clean
#      close / FIN) or `BrokenResourceError` (abrupt close / RST — typical on
#      Windows after TerminateJobObject) because the kernel closes all file
#      descriptors when a process terminates. Either is the direct, OS-level
#      proof that the child is dead.
#
# This replaces an older file-growth-watching approach whose fixed `sleep()`
# durations raced against slow Python interpreter startup on loaded CI runners.


def _connect_back_script(port: int) -> str:
    """Return a ``python -c`` script body that connects to the given port,
    sends ``b'alive'``, then blocks forever. Used by the cleanup tests'
    subprocesses as a liveness probe."""
    return (
        f"import socket, time\n"
        f"s = socket.create_connection(('127.0.0.1', {port}))\n"
        f"s.sendall(b'alive')\n"
        f"time.sleep(3600)\n"
    )


def _spawn_then_block(child_script: str) -> str:
    """Return a ``python -c`` script body that spawns ``child_script`` as a
    subprocess, then blocks forever. The ``!r`` injection avoids nested-quote
    escaping for arbitrary child script content."""
    return (
        f"import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', {child_script!r}])\ntime.sleep(3600)\n"
    )


async def _open_liveness_listener() -> tuple[anyio.abc.SocketListener, int]:
    """Open a TCP listener on localhost and return it along with its port."""
    multi = await anyio.create_tcp_listener(local_host="127.0.0.1")
    sock = multi.listeners[0]
    assert isinstance(sock, anyio.abc.SocketListener)
    addr = sock.extra(anyio.abc.SocketAttribute.local_address)
    # IPv4 local_address is (host: str, port: int)
    assert isinstance(addr, tuple) and len(addr) >= 2 and isinstance(addr[1], int)
    return sock, addr[1]


async def _accept_alive(sock: anyio.abc.SocketListener) -> anyio.abc.SocketStream:
    """Accept one connection and assert the peer sent ``b'alive'``.

    Blocks deterministically until a subprocess connects (no polling). The
    outer test bounds this with ``anyio.fail_after`` to catch the case where
    the subprocess chain failed to start.
    """
    stream = await sock.accept()
    msg = await stream.receive(5)
    assert msg == b"alive", f"expected b'alive', got {msg!r}"
    return stream


async def _assert_stream_closed(stream: anyio.abc.SocketStream) -> None:
    """Assert the peer holding the other end of ``stream`` has terminated.

    When a process dies, the kernel closes its file descriptors including
    sockets. The next ``receive()`` on the peer socket unblocks with one of:

    - ``anyio.EndOfStream`` — clean close (FIN), typical after graceful exit
      or POSIX ``SIGTERM``.
    - ``anyio.BrokenResourceError`` — abrupt close (RST), typical after
      Windows ``TerminateJobObject`` or POSIX ``SIGKILL``.

    Either is a deterministic, kernel-level signal that the process is dead —
    no sleeps or polling required.
    """
    with anyio.fail_after(5.0), pytest.raises((anyio.EndOfStream, anyio.BrokenResourceError)):
        await stream.receive(1)


async def _terminate_and_reap(proc: anyio.abc.Process | FallbackProcess) -> None:
    """Terminate the process tree, reap, and tear down pipe transports.

    ``_terminate_process_tree`` kills the OS process group / Job Object but does
    not call ``process.wait()`` or clean up the asyncio pipe transports. On
    Windows those transports leak and emit ``ResourceWarning`` when GC'd in a
    later test, causing ``PytestUnraisableExceptionWarning`` knock-on failures.

    Production ``stdio.py`` avoids this via its ``stdout_reader`` task which
    reads stdout to EOF (triggering ``_ProactorReadPipeTransport._eof_received``
    → ``close()``) plus ``async with process:`` which waits and closes stdin.
    These tests call ``_terminate_process_tree`` directly, so they replicate
    both parts here: ``wait()`` + close stdin + drain stdout to EOF.

    The stdout drain is the non-obvious part: anyio's ``StreamReaderWrapper.aclose()``
    only marks the Python-level reader closed — it never touches the underlying
    ``_ProactorReadPipeTransport``. That transport starts paused and only detects
    pipe EOF when someone reads, so without a drain it lives until ``__del__``.

    Idempotent: the ``returncode`` guard skips termination if already reaped
    (avoids spurious WARNING/ERROR logs from ``terminate_posix_process_tree``'s
    fallback path, visible because ``log_cli = true``); ``wait()`` and stream
    ``aclose()`` no-op on subsequent calls; the drain raises ``ClosedResourceError``
    on the second call, caught by the suppress. The tests call this explicitly
    as the action under test and ``AsyncExitStack`` calls it again on exit as a
    safety net. Bounded by ``move_on_after`` to prevent hangs.
    """
    with anyio.move_on_after(5.0):
        if proc.returncode is None:
            await _terminate_process_tree(proc)
        await proc.wait()
        assert proc.stdin is not None
        assert proc.stdout is not None
        await proc.stdin.aclose()
        with suppress(anyio.EndOfStream, anyio.BrokenResourceError, anyio.ClosedResourceError):
            await proc.stdout.receive(65536)
        await proc.stdout.aclose()


@pytest.mark.anyio
async def test_basic_child_process_cleanup() -> None:
    """Parent spawns one child; terminating the tree kills both."""
    async with AsyncExitStack() as stack:
        sock, port = await _open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        # Parent spawns a child; the child connects back to us.
        parent_script = _spawn_then_block(_connect_back_script(port))
        proc = await _create_platform_compatible_process(sys.executable, ["-c", parent_script])
        stack.push_async_callback(_terminate_and_reap, proc)

        # Deterministic: accept() blocks until the child connects. No sleep.
        with anyio.fail_after(10.0):
            stream = await _accept_alive(sock)
        stack.push_async_callback(stream.aclose)

        # Terminate, reap and close transports (wraps _terminate_process_tree,
        # the behavior under test).
        await _terminate_and_reap(proc)

        # Deterministic: kernel closed child's socket when it died.
        await _assert_stream_closed(stream)


@pytest.mark.anyio
async def test_nested_process_tree() -> None:
    """Parent → child → grandchild; terminating the tree kills all three."""
    async with AsyncExitStack() as stack:
        sock, port = await _open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        # Build a three-level chain: parent spawns child, child spawns
        # grandchild. Every level connects back to our socket.
        grandchild = _connect_back_script(port)
        child = (
            f"import subprocess, sys\n"
            f"subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n" + _connect_back_script(port)
        )
        parent_script = (
            f"import subprocess, sys\n"
            f"subprocess.Popen([sys.executable, '-c', {child!r}])\n" + _connect_back_script(port)
        )
        proc = await _create_platform_compatible_process(sys.executable, ["-c", parent_script])
        stack.push_async_callback(_terminate_and_reap, proc)

        # Deterministic: three blocking accepts, one per tree level.
        streams: list[anyio.abc.SocketStream] = []
        with anyio.fail_after(10.0):
            for _ in range(3):
                stream = await _accept_alive(sock)
                stack.push_async_callback(stream.aclose)
                streams.append(stream)

        # Terminate the entire tree (wraps _terminate_process_tree).
        await _terminate_and_reap(proc)

        # Every level of the tree must be dead: three kernel-level EOFs.
        for stream in streams:
            await _assert_stream_closed(stream)


@pytest.mark.anyio
async def test_early_parent_exit() -> None:
    """Parent exits immediately on SIGTERM; process-group termination still
    catches the child (exercises the race where the parent dies mid-cleanup).
    """
    async with AsyncExitStack() as stack:
        sock, port = await _open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        # Parent installs a SIGTERM handler that exits immediately, spawns a
        # child that connects back to us, then blocks.
        child = _connect_back_script(port)
        parent_script = (
            f"import signal, subprocess, sys, time\n"
            f"signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
            f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
            f"time.sleep(3600)\n"
        )
        proc = await _create_platform_compatible_process(sys.executable, ["-c", parent_script])
        stack.push_async_callback(_terminate_and_reap, proc)

        # Deterministic: child connected means both parent and child are up.
        with anyio.fail_after(10.0):
            stream = await _accept_alive(sock)
        stack.push_async_callback(stream.aclose)

        # Parent will sys.exit(0) on SIGTERM, but the process-group kill
        # (POSIX killpg / Windows Job Object) must still terminate the child.
        await _terminate_and_reap(proc)

        # Child must be dead despite parent's early exit.
        await _assert_stream_closed(stream)


@pytest.mark.anyio
async def test_stdio_client_universal_cleanup() -> None:
    """Exiting the stdio_client context terminates a process that never exits on its own.

    The child ignores stdin closure (it never reads stdin) and would block for an hour, so
    cleanup must escalate past the stdin-close grace period to terminate it. Death is
    observed through the kernel closing the child's liveness socket; the only time bound is
    a generous hang guard, not a performance claim.
    """
    async with AsyncExitStack() as stack:
        sock, port = await _open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        server_params = StdioServerParameters(command=sys.executable, args=["-c", _connect_back_script(port)])

        # ~2s expected on a healthy run (the stdin-close grace period, then termination).
        with anyio.fail_after(15.0):
            async with stdio_client(server_params) as (_, _):
                stream = await _accept_alive(sock)
                stack.push_async_callback(stream.aclose)

        await _assert_stream_closed(stream)


@pytest.mark.anyio
@pytest.mark.skipif(sys.platform == "win32", reason="Windows signal handling is different")
# Excluded from coverage (lax: exempt from strict-no-cover) because coverage is enforced
# per CI job at 100%, including on Windows runners, where this test is skipped and its
# body would otherwise count as uncovered lines.
async def test_stdio_client_sigterm_ignoring_process() -> None:  # pragma: lax no cover
    """Cleanup escalates past SIGTERM and kills a process that ignores it.

    The child installs SIG_IGN for SIGTERM *before* connecting to the liveness socket, so
    by the time the test proceeds the ignore is guaranteed to be in place. SIGKILL cannot
    be observed by the child; its delivery is proven by the kernel closing the socket.
    """
    async with AsyncExitStack() as stack:
        sock, port = await _open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        script = "import signal\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n" + _connect_back_script(port)
        server_params = StdioServerParameters(command=sys.executable, args=["-c", script])

        # ~4s expected on a healthy run: the stdin-close grace period, then the SIGTERM
        # wait before SIGKILL. The bound is a generous hang guard, not a performance claim.
        with anyio.fail_after(20.0):
            async with stdio_client(server_params) as (_, _):
                stream = await _accept_alive(sock)
                stack.push_async_callback(stream.aclose)

        await _assert_stream_closed(stream)


@pytest.mark.anyio
async def test_stdio_client_graceful_stdin_exit() -> None:
    """A process that exits on stdin closure is cleaned up without any signal.

    The child sends an ``exited`` marker over the liveness socket after observing stdin
    EOF and then exits on its own; receiving the marker proves the exit was stdin-driven.
    A signal-based death (the SIGTERM escalation path) would close the socket without the
    marker ever being sent, failing the assertion.
    """
    async with AsyncExitStack() as stack:
        sock, port = await _open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        script = (
            f"import socket, sys\n"
            f"s = socket.create_connection(('127.0.0.1', {port}))\n"
            f"s.sendall(b'alive')\n"
            f"sys.stdin.buffer.read()\n"
            f"s.sendall(b'exited')\n"
        )
        server_params = StdioServerParameters(command=sys.executable, args=["-c", script])

        with anyio.fail_after(15.0):
            async with stdio_client(server_params) as (_, _):
                stream = await _accept_alive(sock)
                stack.push_async_callback(stream.aclose)

        # Read until the kernel-level EOF that accompanies the child's death; everything
        # received must be the marker the child sends only on the stdin-EOF exit path.
        received = b""
        with anyio.fail_after(5.0):
            with suppress(anyio.EndOfStream, anyio.BrokenResourceError):
                while True:
                    received += await stream.receive(16)
        assert received == b"exited"


@pytest.mark.anyio
async def test_stdio_client_stdin_close_ignored() -> None:
    """When a process ignores stdin closure, shutdown waits out the grace period and
    then escalates to termination.

    The lower bound on the cleanup duration pins the genuine time-based contract: the
    escalation must not fire before the stdin-close grace period elapses. There is
    deliberately no upper bound — on a slow runner cleanup only takes longer, which
    proves nothing about the escalation logic.
    """
    async with AsyncExitStack() as stack:
        sock, port = await _open_liveness_listener()
        stack.push_async_callback(sock.aclose)

        # The child installs a SIGTERM handler that exits cleanly, then connects, then
        # blocks forever without ever reading stdin; the liveness handshake guarantees
        # the handler is installed before cleanup can send SIGTERM.
        script = "import signal, sys\nsignal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n" + _connect_back_script(
            port
        )
        server_params = StdioServerParameters(command=sys.executable, args=["-c", script])

        with anyio.fail_after(15.0):
            async with stdio_client(server_params) as (_, _):
                stream = await _accept_alive(sock)
                stack.push_async_callback(stream.aclose)
                cleanup_started = time.monotonic()
            cleanup_elapsed = time.monotonic() - cleanup_started

        await _assert_stream_closed(stream)

        # The cleanup contains a full PROCESS_TERMINATION_TIMEOUT wait for the process to
        # exit on stdin closure (which this child never does); a small slop absorbs timer
        # granularity. An early escalation would finish well under the grace period.
        assert cleanup_elapsed > PROCESS_TERMINATION_TIMEOUT - 0.1, (
            f"cleanup finished in {cleanup_elapsed:.2f}s, faster than the "
            f"{PROCESS_TERMINATION_TIMEOUT}s stdin-close grace period — escalation fired early"
        )
