import errno
import shutil
import sys
import textwrap
import time
from contextlib import AsyncExitStack, suppress
from pathlib import Path

import anyio
import anyio.abc
import pytest

from mcp.client.session import ClientSession
from mcp.client.stdio import (
    StdioServerParameters,
    _create_platform_compatible_process,
    _terminate_process_tree,
    stdio_client,
)
from mcp.os.win32.utilities import FallbackProcess
from mcp.shared.exceptions import MCPError
from mcp.shared.message import SessionMessage
from mcp.types import CONNECTION_CLOSED, JSONRPCMessage, JSONRPCRequest, JSONRPCResponse

# Timeout for cleanup of processes that ignore SIGTERM
# This timeout ensures the test fails quickly if the cleanup logic doesn't have
# proper fallback mechanisms (SIGINT/SIGKILL) for processes that ignore SIGTERM
SIGTERM_IGNORING_PROCESS_TIMEOUT = 5.0

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
async def test_stdio_client_invalid_utf8_from_server_does_not_crash(tmp_path: Path):
    """A buggy child server should surface malformed UTF-8 as an in-stream error.

    The client should continue reading subsequent valid JSON-RPC lines instead of
    crashing the whole transport task group during decoding.
    """
    script = tmp_path / "bad_stdout_server.py"
    valid = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    script.write_text(
        textwrap.dedent(
            f"""\
            import sys
            import time

            sys.stdout.buffer.write(b"\\xff\\xfe\\n")
            sys.stdout.buffer.write({valid.model_dump_json(by_alias=True, exclude_none=True)!r}.encode() + b"\\n")
            sys.stdout.buffer.flush()
            time.sleep(0.2)
            """
        )
    )

    server_params = StdioServerParameters(command=sys.executable, args=[str(script)])

    with anyio.fail_after(5):
        async with stdio_client(server_params) as (read_stream, write_stream):
            await write_stream.aclose()
            first = await read_stream.receive()
            assert isinstance(first, Exception)

            second = await read_stream.receive()
            assert isinstance(second, SessionMessage)
            assert second.message == valid


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


@pytest.mark.anyio
async def test_stdio_client_universal_cleanup():
    """Test that stdio_client completes cleanup within reasonable time
    even when connected to processes that exit slowly.
    """

    # Use a Python script that simulates a long-running process
    # This ensures consistent behavior across platforms
    long_running_script = textwrap.dedent(
        """
        import time
        import sys

        # Simulate a long-running process
        for i in range(100):
            time.sleep(0.1)
            # Flush to ensure output is visible
            sys.stdout.flush()
            sys.stderr.flush()
        """
    )

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-c", long_running_script],
    )

    start_time = time.time()

    with anyio.move_on_after(8.0) as cancel_scope:
        async with stdio_client(server_params) as (_, _):
            # Immediately exit - this triggers cleanup while process is still running
            pass

        end_time = time.time()
        elapsed = end_time - start_time

        # On Windows: 2s (stdin wait) + 2s (terminate wait) + overhead = ~5s expected
        assert elapsed < 6.0, (
            f"stdio_client cleanup took {elapsed:.1f} seconds, expected < 6.0 seconds. "
            f"This suggests the timeout mechanism may not be working properly."
        )

    # Check if we timed out
    if cancel_scope.cancelled_caught:  # pragma: no cover
        pytest.fail(
            "stdio_client cleanup timed out after 8.0 seconds. "
            "This indicates the cleanup mechanism is hanging and needs fixing."
        )


@pytest.mark.anyio
@pytest.mark.skipif(sys.platform == "win32", reason="Windows signal handling is different")
async def test_stdio_client_sigint_only_process():  # pragma: lax no cover
    """Test cleanup with a process that ignores SIGTERM but responds to SIGINT."""
    # Create a Python script that ignores SIGTERM but handles SIGINT
    script_content = textwrap.dedent(
        """
        import signal
        import sys
        import time

        # Ignore SIGTERM (what process.terminate() sends)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

        # Handle SIGINT (Ctrl+C signal) by exiting cleanly
        def sigint_handler(signum, frame):
            sys.exit(0)

        signal.signal(signal.SIGINT, sigint_handler)

        # Keep running until SIGINT received
        while True:
            time.sleep(0.1)
        """
    )

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-c", script_content],
    )

    start_time = time.time()

    try:
        # Use anyio timeout to prevent test from hanging forever
        with anyio.move_on_after(5.0) as cancel_scope:
            async with stdio_client(server_params) as (_, _):
                # Let the process start and begin ignoring SIGTERM
                await anyio.sleep(0.5)
                # Exit context triggers cleanup - this should not hang
                pass

        if cancel_scope.cancelled_caught:  # pragma: no cover
            raise TimeoutError("Test timed out")

        end_time = time.time()
        elapsed = end_time - start_time

        # Should complete quickly even with SIGTERM-ignoring process
        # This will fail if cleanup only uses process.terminate() without fallback
        assert elapsed < SIGTERM_IGNORING_PROCESS_TIMEOUT, (
            f"stdio_client cleanup took {elapsed:.1f} seconds with SIGTERM-ignoring process. "
            f"Expected < {SIGTERM_IGNORING_PROCESS_TIMEOUT} seconds. "
            "This suggests the cleanup needs SIGINT/SIGKILL fallback."
        )
    except (TimeoutError, Exception) as e:  # pragma: no cover
        if isinstance(e, TimeoutError) or "timed out" in str(e):
            pytest.fail(
                f"stdio_client cleanup timed out after {SIGTERM_IGNORING_PROCESS_TIMEOUT} seconds "
                "with SIGTERM-ignoring process. "
                "This confirms the cleanup needs SIGINT/SIGKILL fallback for processes that ignore SIGTERM."
            )
        else:
            raise


# ---------------------------------------------------------------------------
# TestChildProcessCleanup — socket-based deterministic child liveness probe
# ---------------------------------------------------------------------------
#
# These tests verify that `_terminate_process_tree()` kills the *entire* process
# tree (not just the immediate child), which is critical for cleaning up tools
# like `npx` that spawn their own subprocesses.
#
# Mechanism: each subprocess in the tree connects a TCP socket back to a
# listener owned by the test. We then use two kernel-guaranteed blocking-I/O
# signals — neither requires any `sleep()` or polling loop:
#
#   1. `await listener.accept()` blocks until the subprocess connects,
#      proving it is running.
#   2. After `_terminate_process_tree()`, `await stream.receive(1)` raises
#      `EndOfStream` (clean close / FIN) or `BrokenResourceError` (abrupt
#      close / RST — typical on Windows after TerminateJobObject) because the
#      kernel closes all file descriptors when a process terminates. Either
#      is the direct, OS-level proof that the child is dead.
#
# This replaces an older file-growth-watching approach whose fixed `sleep()`
# durations raced against slow Python interpreter startup on loaded CI runners.


def _connect_back_script(port: int) -> str:
    """Return a ``python -c`` script body that connects to the given port,
    sends ``b'alive'``, then blocks forever. Used by TestChildProcessCleanup
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


class TestChildProcessCleanup:
    """Integration tests for ``_terminate_process_tree`` covering basic,
    nested, and early-parent-exit process tree scenarios. See module-level
    comment above for the socket-based liveness probe mechanism.
    """

    @pytest.mark.anyio
    async def test_basic_child_process_cleanup(self):
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
    async def test_nested_process_tree(self):
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
    async def test_early_parent_exit(self):
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
async def test_stdio_client_graceful_stdin_exit():
    """Test that a process exits gracefully when stdin is closed,
    without needing SIGTERM or SIGKILL.
    """
    # Create a Python script that exits when stdin is closed
    script_content = textwrap.dedent(
        """
        import sys

        # Read from stdin until it's closed
        try:
            while True:
                line = sys.stdin.readline()
                if not line:  # EOF/stdin closed
                    break
        except:
            pass

        # Exit gracefully
        sys.exit(0)
        """
    )

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-c", script_content],
    )

    start_time = time.time()

    # Use anyio timeout to prevent test from hanging forever
    with anyio.move_on_after(5.0) as cancel_scope:
        async with stdio_client(server_params) as (_, _):
            # Let the process start and begin reading stdin
            await anyio.sleep(0.2)
            # Exit context triggers cleanup - process should exit from stdin closure
            pass

    if cancel_scope.cancelled_caught:
        pytest.fail(
            "stdio_client cleanup timed out after 5.0 seconds. "
            "Process should have exited gracefully when stdin was closed."
        )  # pragma: no cover

    end_time = time.time()
    elapsed = end_time - start_time

    # Should complete quickly with just stdin closure (no signals needed)
    assert elapsed < 3.0, (
        f"stdio_client cleanup took {elapsed:.1f} seconds for stdin-aware process. "
        f"Expected < 3.0 seconds since process should exit on stdin closure."
    )


@pytest.mark.anyio
async def test_stdio_client_stdin_close_ignored():
    """Test that when a process ignores stdin closure, the shutdown sequence
    properly escalates to SIGTERM.
    """
    # Create a Python script that ignores stdin closure but responds to SIGTERM
    script_content = textwrap.dedent(
        """
        import signal
        import sys
        import time

        # Set up SIGTERM handler to exit cleanly
        def sigterm_handler(signum, frame):
            sys.exit(0)

        signal.signal(signal.SIGTERM, sigterm_handler)

        # Close stdin immediately to simulate ignoring it
        sys.stdin.close()

        # Keep running until SIGTERM
        while True:
            time.sleep(0.1)
        """
    )

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-c", script_content],
    )

    start_time = time.time()

    # Use anyio timeout to prevent test from hanging forever
    with anyio.move_on_after(7.0) as cancel_scope:
        async with stdio_client(server_params) as (_, _):
            # Let the process start
            await anyio.sleep(0.2)
            # Exit context triggers cleanup
            pass

    if cancel_scope.cancelled_caught:
        pytest.fail(
            "stdio_client cleanup timed out after 7.0 seconds. "
            "Process should have been terminated via SIGTERM escalation."
        )  # pragma: no cover

    end_time = time.time()
    elapsed = end_time - start_time

    # Should take ~2 seconds (stdin close timeout) before SIGTERM is sent
    # Total time should be between 2-4 seconds
    assert 1.5 < elapsed < 4.5, (
        f"stdio_client cleanup took {elapsed:.1f} seconds for stdin-ignoring process. "
        f"Expected between 2-4 seconds (2s stdin timeout + termination time)."
    )
