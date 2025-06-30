import shutil
import sys
import textwrap
import time

import anyio
import pytest

from mcp.client.session import ClientSession
from mcp.client.stdio import (
    StdioServerParameters,
    stdio_client,
)
from mcp.shared.exceptions import McpError
from mcp.shared.message import SessionMessage
from mcp.types import CONNECTION_CLOSED, JSONRPCMessage, JSONRPCRequest, JSONRPCResponse

tee: str = shutil.which("tee")  # type: ignore
python: str = shutil.which("python")  # type: ignore


@pytest.mark.anyio
@pytest.mark.skipif(tee is None, reason="could not find tee command")
async def test_stdio_context_manager_exiting():
    async with stdio_client(StdioServerParameters(command=tee)) as (_, _):
        pass


@pytest.mark.anyio
@pytest.mark.skipif(tee is None, reason="could not find tee command")
async def test_stdio_client():
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

        read_messages = []
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
        async with stdio_client(server_params) as (read_stream, write_stream):
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
            async with stdio_client(server_params) as (read_stream, write_stream):
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
        assert elapsed < 5.0, (
            f"stdio_client cleanup took {elapsed:.1f} seconds with SIGTERM-ignoring process. "
            f"Expected < 5.0 seconds. This suggests the cleanup needs SIGINT/SIGKILL fallback."
        )
    except (TimeoutError, Exception) as e:
        if isinstance(e, TimeoutError) or "timed out" in str(e):
            pytest.fail(
                "stdio_client cleanup timed out after 5.0 seconds with SIGTERM-ignoring process. "
                "This confirms the cleanup needs SIGINT/SIGKILL fallback for processes that ignore SIGTERM."
            )
        else:
            raise


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
        async with stdio_client(server_params) as (read_stream, write_stream):
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
        async with stdio_client(server_params) as (read_stream, write_stream):
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
