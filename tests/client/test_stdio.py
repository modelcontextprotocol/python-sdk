import os
import shutil
import sys
import tempfile
import textwrap
import time

import anyio
import pytest

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, _create_platform_compatible_process, stdio_client
from mcp.shared.exceptions import McpError
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
            JSONRPCMessage(root=JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")),
            JSONRPCMessage(root=JSONRPCResponse(jsonrpc="2.0", id=2, result={})),
        ]

        async with write_stream:
            for message in messages:
                session_message = SessionMessage(message)
                await write_stream.send(session_message)

        read_messages: list[JSONRPCMessage] = []
        async with read_stream:
            async for message in read_stream:
                if isinstance(message, Exception):
                    raise message

                read_messages.append(message.message)
                if len(read_messages) == 2:
                    break

        assert len(read_messages) == 2
        assert read_messages[0] == JSONRPCMessage(root=JSONRPCRequest(jsonrpc="2.0", id=1, method="ping"))
        assert read_messages[1] == JSONRPCMessage(root=JSONRPCResponse(jsonrpc="2.0", id=2, result={}))


@pytest.mark.anyio
async def test_stdio_client_bad_path():
    """Check that the connection doesn't hang if process errors."""
    server_params = StdioServerParameters(command="python", args=["-c", "non-existent-file.py"])
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # The session should raise an error when the connection closes
            with pytest.raises(McpError) as exc_info:
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
    with pytest.raises(Exception) as exc_info:
        async with stdio_client(server_params) as (_, _):
            pass

    # The error should indicate the command was not found
    error_message = str(exc_info.value)
    assert (
        "nonexistent" in error_message
        or "not found" in error_message.lower()
        or "cannot find the file" in error_message.lower()  # Windows error message
    )


@pytest.mark.anyio
async def test_stdio_client_universal_cleanup():
    """
    Test that stdio_client completes cleanup within reasonable time
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
    if cancel_scope.cancelled_caught:
        pytest.fail(
            "stdio_client cleanup timed out after 8.0 seconds. "
            "This indicates the cleanup mechanism is hanging and needs fixing."
        )


@pytest.mark.anyio
@pytest.mark.skipif(sys.platform == "win32", reason="Windows signal handling is different")
async def test_stdio_client_sigint_only_process():
    """
    Test cleanup with a process that ignores SIGTERM but responds to SIGINT.
    """
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

        if cancel_scope.cancelled_caught:
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
    except (TimeoutError, Exception) as e:
        if isinstance(e, TimeoutError) or "timed out" in str(e):
            pytest.fail(
                f"stdio_client cleanup timed out after {SIGTERM_IGNORING_PROCESS_TIMEOUT} seconds "
                "with SIGTERM-ignoring process. "
                "This confirms the cleanup needs SIGINT/SIGKILL fallback for processes that ignore SIGTERM."
            )
        else:
            raise


class TestChildProcessCleanup:
    """
    Tests for child process cleanup functionality using _terminate_process_tree.

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
        """
        Test basic parent-child process cleanup.
        Parent spawns a single child process that writes continuously to a file.
        """
        # Create a marker file for the child process to write to
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            marker_file = f.name

        # Also create a file to verify parent started
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            parent_marker = f.name

        try:
            # Parent script that spawns a child process
            parent_script = textwrap.dedent(
                f"""
                import subprocess
                import sys
                import time
                import os

                # Mark that parent started
                with open({escape_path_for_python(parent_marker)}, 'w') as f:
                    f.write('parent started\\n')

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

            print("\nStarting child process termination test...")

            # Start the parent process
            proc = await _create_platform_compatible_process(sys.executable, ["-c", parent_script])

            # Wait for processes to start
            await anyio.sleep(0.5)

            # Verify parent started
            assert os.path.exists(parent_marker), "Parent process didn't start"

            # Verify child is writing
            if os.path.exists(marker_file):
                initial_size = os.path.getsize(marker_file)
                await anyio.sleep(0.3)
                size_after_wait = os.path.getsize(marker_file)
                assert size_after_wait > initial_size, "Child process should be writing"
                print(f"Child is writing (file grew from {initial_size} to {size_after_wait} bytes)")

            # Terminate using our function
            print("Terminating process and children...")
            from mcp.client.stdio import _terminate_process_tree

            await _terminate_process_tree(proc)

            # Verify processes stopped
            await anyio.sleep(0.5)
            if os.path.exists(marker_file):
                size_after_cleanup = os.path.getsize(marker_file)
                await anyio.sleep(0.5)
                final_size = os.path.getsize(marker_file)

                print(f"After cleanup: file size {size_after_cleanup} -> {final_size}")
                assert final_size == size_after_cleanup, (
                    f"Child process still running! File grew by {final_size - size_after_cleanup} bytes"
                )

            print("SUCCESS: Child process was properly terminated")

        finally:
            # Clean up files
            for f in [marker_file, parent_marker]:
                try:
                    os.unlink(f)
                except OSError:
                    pass

    @pytest.mark.anyio
    @pytest.mark.filterwarnings("ignore::ResourceWarning" if sys.platform == "win32" else "default")
    async def test_nested_process_tree(self):
        """
        Test nested process tree cleanup (parent → child → grandchild).
        Each level writes to a different file to verify all processes are terminated.
        """
        # Create temporary files for each process level
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f1:
            parent_file = f1.name
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f2:
            child_file = f2.name
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f3:
            grandchild_file = f3.name

        try:
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

            # Start the parent process
            proc = await _create_platform_compatible_process(sys.executable, ["-c", parent_script])

            # Let all processes start
            await anyio.sleep(1.0)

            # Verify all are writing
            for file_path, name in [(parent_file, "parent"), (child_file, "child"), (grandchild_file, "grandchild")]:
                if os.path.exists(file_path):
                    initial_size = os.path.getsize(file_path)
                    await anyio.sleep(0.3)
                    new_size = os.path.getsize(file_path)
                    assert new_size > initial_size, f"{name} process should be writing"

            # Terminate the whole tree
            from mcp.client.stdio import _terminate_process_tree

            await _terminate_process_tree(proc)

            # Verify all stopped
            await anyio.sleep(0.5)
            for file_path, name in [(parent_file, "parent"), (child_file, "child"), (grandchild_file, "grandchild")]:
                if os.path.exists(file_path):
                    size1 = os.path.getsize(file_path)
                    await anyio.sleep(0.3)
                    size2 = os.path.getsize(file_path)
                    assert size1 == size2, f"{name} still writing after cleanup!"

            print("SUCCESS: All processes in tree terminated")

        finally:
            # Clean up all marker files
            for f in [parent_file, child_file, grandchild_file]:
                try:
                    os.unlink(f)
                except OSError:
                    pass

    @pytest.mark.anyio
    @pytest.mark.filterwarnings("ignore::ResourceWarning" if sys.platform == "win32" else "default")
    async def test_early_parent_exit(self):
        """
        Test cleanup when parent exits during termination sequence.
        Tests the race condition where parent might die during our termination
        sequence but we can still clean up the children via the process group.
        """
        # Create a temporary file for the child
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            marker_file = f.name

        try:
            # Parent that spawns child and waits briefly
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

                # Parent waits a bit then exits on SIGTERM
                def handle_term(sig, frame):
                    sys.exit(0)

                signal.signal(signal.SIGTERM, handle_term)

                # Wait
                while True:
                    time.sleep(0.1)
                """
            )

            # Start the parent process
            proc = await _create_platform_compatible_process(sys.executable, ["-c", parent_script])

            # Let child start writing
            await anyio.sleep(0.5)

            # Verify child is writing
            if os.path.exists(marker_file):
                size1 = os.path.getsize(marker_file)
                await anyio.sleep(0.3)
                size2 = os.path.getsize(marker_file)
                assert size2 > size1, "Child should be writing"

            # Terminate - this will kill the process group even if parent exits first
            from mcp.client.stdio import _terminate_process_tree

            await _terminate_process_tree(proc)

            # Verify child stopped
            await anyio.sleep(0.5)
            if os.path.exists(marker_file):
                size3 = os.path.getsize(marker_file)
                await anyio.sleep(0.3)
                size4 = os.path.getsize(marker_file)
                assert size3 == size4, "Child should be terminated"

            print("SUCCESS: Child terminated even with parent exit during cleanup")

        finally:
            # Clean up marker file
            try:
                os.unlink(marker_file)
            except OSError:
                pass


@pytest.mark.anyio
async def test_stdio_client_graceful_stdin_exit():
    """
    Test that a process exits gracefully when stdin is closed,
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
        )

    end_time = time.time()
    elapsed = end_time - start_time

    # Should complete quickly with just stdin closure (no signals needed)
    assert elapsed < 3.0, (
        f"stdio_client cleanup took {elapsed:.1f} seconds for stdin-aware process. "
        f"Expected < 3.0 seconds since process should exit on stdin closure."
    )


@pytest.mark.anyio
async def test_stdio_client_stdin_close_ignored():
    """
    Test that when a process ignores stdin closure, the shutdown sequence
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
        )

    end_time = time.time()
    elapsed = end_time - start_time

    # Should take ~2 seconds (stdin close timeout) before SIGTERM is sent
    # Total time should be between 2-4 seconds
    assert 1.5 < elapsed < 4.5, (
        f"stdio_client cleanup took {elapsed:.1f} seconds for stdin-ignoring process. "
        f"Expected between 2-4 seconds (2s stdin timeout + termination time)."
    )
