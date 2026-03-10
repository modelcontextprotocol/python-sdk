import errno
import os
import shutil
import sys
import tempfile
import textwrap
import time

import anyio
import pytest

from mcp.client.session import ClientSession
from mcp.client.stdio import (
    StdioServerParameters,
    _create_platform_compatible_process,
    _terminate_process_tree,
    stdio_client,
)
from mcp.shared.exceptions import MCPError
from mcp.shared.message import SessionMessage
from mcp.types import CONNECTION_CLOSED, JSONRPCMessage, JSONRPCRequest, JSONRPCResponse

from ..shared.test_win32_utils import escape_path_for_python

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


async def _wait_for_file_size(path: str, larger_than: int = 0, *, timeout: float = 10.0) -> int:
    """Poll until the file at ``path`` has size strictly greater than ``larger_than``.

    Returns the observed size once the threshold is crossed. Raises ``TimeoutError``
    (via ``anyio.fail_after``) if the file does not grow past the threshold within
    ``timeout`` seconds. Used by ``TestChildProcessCleanup`` to deterministically
    wait for subprocess chains to start writing, replacing fixed ``sleep()`` durations
    that caused flakiness on loaded CI runners.
    """
    with anyio.fail_after(timeout):
        while os.path.getsize(path) <= larger_than:
            await anyio.sleep(0.05)
    return os.path.getsize(path)


class TestChildProcessCleanup:
    """Tests for child process cleanup functionality using _terminate_process_tree.

    These tests verify that child processes are properly terminated when the parent
    is killed, addressing the issue where processes like npx spawn child processes
    that need to be cleaned up. The tests cover various process tree scenarios:

    - Basic parent-child relationship (single child process)
    - Multi-level process trees (parent → child → grandchild)
    - Race conditions where parent exits during cleanup

    Note on Windows ResourceWarning:
    On Windows, we may see ResourceWarning about subprocess still running. This is
    expected behavior due to how Windows process termination works:
    - anyio's process.terminate() calls Windows TerminateProcess() API
    - TerminateProcess() immediately kills the process without allowing cleanup
    - subprocess.Popen objects in the killed process can't run their cleanup code
    - Python detects this during garbage collection and issues a ResourceWarning

    This warning does NOT indicate a process leak - the processes are properly
    terminated. It only means the Popen objects couldn't clean up gracefully.
    This is a fundamental difference between Windows and Unix process termination.
    """

    @pytest.mark.anyio
    @pytest.mark.filterwarnings("ignore::ResourceWarning" if sys.platform == "win32" else "default")
    async def test_basic_child_process_cleanup(self):
        """Test basic parent-child process cleanup.
        Parent spawns a single child process that writes continuously to a file.
        """
        # Create a marker file for the child process to write to
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            marker_file = f.name

        # Parent script that spawns a child process
        parent_script = textwrap.dedent(
            f"""
            import subprocess
            import sys
            import time

            # Child script that writes continuously
            child_script = f'''
            import time
            with open({escape_path_for_python(marker_file)}, 'a') as f:
                while True:
                    f.write(f"{time.time()}")
                    f.flush()
                    time.sleep(0.1)
            '''

            # Start the child process
            child = subprocess.Popen([sys.executable, '-c', child_script])

            # Parent just sleeps
            while True:
                time.sleep(0.1)
            """
        )

        proc = None
        try:
            proc = await _create_platform_compatible_process(sys.executable, ["-c", parent_script])

            # Poll for child to start writing (bounded wait replaces fixed sleep(0.5)+sleep(0.3))
            initial_size = await _wait_for_file_size(marker_file, larger_than=0)
            # Poll for further growth to confirm the child is actively writing in a loop
            grown_size = await _wait_for_file_size(marker_file, larger_than=initial_size)
            print(f"Child is writing (file grew from {initial_size} to {grown_size} bytes)")

            # Terminate using our function (the behavior under test)
            await _terminate_process_tree(proc)
            proc = None  # Successfully terminated; skip redundant cleanup in finally

            # Verify child stopped writing. _terminate_process_tree on POSIX already polls
            # for process group death; a single 0.3s check (3x child write interval) suffices.
            size_after_term = os.path.getsize(marker_file)
            await anyio.sleep(0.3)
            final_size = os.path.getsize(marker_file)
            assert final_size == size_after_term, (
                f"Child process still running! File grew by {final_size - size_after_term} bytes"
            )

        finally:
            # Ensure process tree is terminated even if an assertion above failed,
            # preventing leaked subprocesses from causing knock-on failures in later tests.
            if proc is not None:  # pragma: no cover
                # Only reached if an assertion failed before _terminate_process_tree;
                # ensures the subprocess tree doesn't leak into later tests.
                with anyio.move_on_after(5.0):
                    await _terminate_process_tree(proc)
            try:
                os.unlink(marker_file)
            except OSError:  # pragma: no cover
                pass

    @pytest.mark.anyio
    @pytest.mark.filterwarnings("ignore::ResourceWarning" if sys.platform == "win32" else "default")
    async def test_nested_process_tree(self):
        """Test nested process tree cleanup (parent → child → grandchild).
        Each level writes to a different file to verify all processes are terminated.
        """
        # Create temporary files for each process level
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f1:
            parent_file = f1.name
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f2:
            child_file = f2.name
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f3:
            grandchild_file = f3.name

        # Simple nested process tree test
        # We create parent -> child -> grandchild, each writing to a file
        parent_script = textwrap.dedent(
            f"""
            import subprocess
            import sys
            import time
            import os

            # Child will spawn grandchild and write to child file
            child_script = f'''import subprocess
            import sys
            import time

            # Grandchild just writes to file
            grandchild_script = \"\"\"import time
            with open({escape_path_for_python(grandchild_file)}, 'a') as f:
                while True:
                    f.write(f"gc {{time.time()}}")
                    f.flush()
                    time.sleep(0.1)\"\"\"

            # Spawn grandchild
            subprocess.Popen([sys.executable, '-c', grandchild_script])

            # Child writes to its file
            with open({escape_path_for_python(child_file)}, 'a') as f:
                while True:
                    f.write(f"c {time.time()}")
                    f.flush()
                    time.sleep(0.1)'''

            # Spawn child process
            subprocess.Popen([sys.executable, '-c', child_script])

            # Parent writes to its file
            with open({escape_path_for_python(parent_file)}, 'a') as f:
                while True:
                    f.write(f"p {time.time()}")
                    f.flush()
                    time.sleep(0.1)
            """
        )

        files = [(parent_file, "parent"), (child_file, "child"), (grandchild_file, "grandchild")]
        proc = None
        try:
            proc = await _create_platform_compatible_process(sys.executable, ["-c", parent_script])

            # Poll for each level of the tree to start writing (bounded wait).
            # Grandchild is deepest, so once it's writing, the whole chain is up.
            for file_path, name in files:
                size = await _wait_for_file_size(file_path, larger_than=0)
                await _wait_for_file_size(file_path, larger_than=size)
                print(f"{name} is writing")

            # Terminate the whole tree (the behavior under test)
            await _terminate_process_tree(proc)
            proc = None  # Successfully terminated; skip redundant cleanup in finally

            # Verify all stopped. Record sizes once, wait 3x write interval, check none grew.
            sizes_after_term = {path: os.path.getsize(path) for path, _ in files}
            await anyio.sleep(0.3)
            for file_path, name in files:
                final_size = os.path.getsize(file_path)
                assert final_size == sizes_after_term[file_path], f"{name} still writing after cleanup!"

        finally:
            # Ensure process tree is terminated even if an assertion above failed.
            if proc is not None:  # pragma: no cover
                # Only reached if an assertion failed before _terminate_process_tree;
                # ensures the subprocess tree doesn't leak into later tests.
                with anyio.move_on_after(5.0):
                    await _terminate_process_tree(proc)
            for f in [parent_file, child_file, grandchild_file]:
                try:
                    os.unlink(f)
                except OSError:  # pragma: no cover
                    pass

    @pytest.mark.anyio
    @pytest.mark.filterwarnings("ignore::ResourceWarning" if sys.platform == "win32" else "default")
    async def test_early_parent_exit(self):
        """Test cleanup when parent exits during termination sequence.
        Tests the race condition where parent might die during our termination
        sequence but we can still clean up the children via the process group.
        """
        # Create a temporary file for the child
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            marker_file = f.name

        # Parent that spawns child and exits immediately on SIGTERM
        parent_script = textwrap.dedent(
            f"""
            import subprocess
            import sys
            import time
            import signal

            # Child that continues running
            child_script = f'''import time
            with open({escape_path_for_python(marker_file)}, 'a') as f:
                while True:
                    f.write(f"child {time.time()}")
                    f.flush()
                    time.sleep(0.1)'''

            # Start child in same process group
            subprocess.Popen([sys.executable, '-c', child_script])

            # Parent exits immediately on SIGTERM (the race this test exercises)
            def handle_term(sig, frame):
                sys.exit(0)

            signal.signal(signal.SIGTERM, handle_term)

            # Wait
            while True:
                time.sleep(0.1)
            """
        )

        proc = None
        try:
            proc = await _create_platform_compatible_process(sys.executable, ["-c", parent_script])

            # Poll for child to start writing (bounded wait)
            initial_size = await _wait_for_file_size(marker_file, larger_than=0)
            await _wait_for_file_size(marker_file, larger_than=initial_size)

            # Terminate — parent exits immediately on SIGTERM, but process group kill
            # should still catch the child
            await _terminate_process_tree(proc)
            proc = None  # Successfully terminated; skip redundant cleanup in finally

            # Verify child stopped writing
            size_after_term = os.path.getsize(marker_file)
            await anyio.sleep(0.3)
            final_size = os.path.getsize(marker_file)
            assert final_size == size_after_term, "Child should be terminated"

        finally:
            # Ensure process tree is terminated even if an assertion above failed.
            if proc is not None:  # pragma: no cover
                # Only reached if an assertion failed before _terminate_process_tree;
                # ensures the subprocess tree doesn't leak into later tests.
                with anyio.move_on_after(5.0):
                    await _terminate_process_tree(proc)
            try:
                os.unlink(marker_file)
            except OSError:  # pragma: no cover
                pass


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
