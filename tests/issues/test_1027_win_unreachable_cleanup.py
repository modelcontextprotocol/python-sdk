"""
Regression test for issue #1027: Ensure cleanup procedures run properly during shutdown

Issue #1027 reported that cleanup code after "yield" in lifespan was unreachable when
processes were terminated. This has been fixed by implementing the MCP spec-compliant
stdio shutdown sequence that closes stdin first, allowing graceful exit.

These tests verify the fix continues to work correctly across all platforms.
"""

import sys
import tempfile
import textwrap
from pathlib import Path

import anyio
import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import _create_platform_compatible_process, stdio_client
from tests.shared.test_win32_utils import escape_path_for_python


@pytest.mark.anyio
async def test_lifespan_cleanup_executed():
    """
    Regression test ensuring MCP server cleanup code runs during shutdown.

    This test verifies that the fix for issue #1027 works correctly by:
    1. Starting an MCP server that writes a marker file on startup
    2. Shutting down the server normally via stdio_client
    3. Verifying the cleanup code (after yield) executed and wrote its marker file

    The fix implements proper stdin closure before termination, giving servers
    time to run their cleanup handlers.
    """

    # Create marker files to track server lifecycle
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        startup_marker = f.name
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        cleanup_marker = f.name

    # Remove the files so we can detect when they're created
    Path(startup_marker).unlink()
    Path(cleanup_marker).unlink()

    # Create a minimal MCP server using FastMCP that tracks lifecycle
    server_code = textwrap.dedent(f"""
        import asyncio
        import sys
        from pathlib import Path
        from contextlib import asynccontextmanager
        from mcp.server.fastmcp import FastMCP
        
        STARTUP_MARKER = {escape_path_for_python(startup_marker)}
        CLEANUP_MARKER = {escape_path_for_python(cleanup_marker)}
        
        @asynccontextmanager
        async def lifespan(server):
            # Write startup marker
            Path(STARTUP_MARKER).write_text("started")
            try:
                yield {{"started": True}}
            finally:
                # This cleanup code now runs properly during shutdown
                Path(CLEANUP_MARKER).write_text("cleaned up")
        
        mcp = FastMCP("test-server", lifespan=lifespan)
        
        @mcp.tool()
        def echo(text: str) -> str:
            return text
        
        if __name__ == "__main__":
            mcp.run()
    """)

    # Write the server script to a temporary file
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
        server_script = f.name
        f.write(server_code)

    try:
        # Launch the MCP server
        params = StdioServerParameters(command=sys.executable, args=[server_script])

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize the session
                result = await session.initialize()
                assert result.protocolVersion in ["2024-11-05", "2025-06-18"]

                # Verify startup marker was created
                assert Path(startup_marker).exists(), "Server startup marker not created"
                assert Path(startup_marker).read_text() == "started"

                # Make a test request to ensure server is working
                response = await session.call_tool("echo", {"text": "hello"})
                assert response.content[0].type == "text"
                assert getattr(response.content[0], "text") == "hello"

                # Session will be closed when exiting the context manager

        # Give server a moment to complete cleanup
        with anyio.move_on_after(5.0):
            while not Path(cleanup_marker).exists():
                await anyio.sleep(0.1)

        # Verify cleanup marker was created - this works now that stdio_client
        # properly closes stdin before termination, allowing graceful shutdown
        assert Path(cleanup_marker).exists(), "Server cleanup marker not created - regression in issue #1027 fix"
        assert Path(cleanup_marker).read_text() == "cleaned up"

    finally:
        # Clean up files
        for path in [server_script, startup_marker, cleanup_marker]:
            try:
                Path(path).unlink()
            except FileNotFoundError:
                pass


@pytest.mark.anyio
@pytest.mark.filterwarnings("ignore::ResourceWarning" if sys.platform == "win32" else "default")
async def test_stdin_close_triggers_cleanup():
    """
    Regression test verifying the stdin-based graceful shutdown mechanism.

    This test ensures the core fix for issue #1027 continues to work by:
    1. Manually managing a server process
    2. Closing stdin to trigger graceful shutdown
    3. Verifying cleanup handlers run before the process exits

    This mimics the behavior now implemented in stdio_client's shutdown sequence.

    Note on Windows ResourceWarning:
    On Windows, we may see ResourceWarning about unclosed file descriptors.
    This is expected behavior because:
    - We're manually managing the process lifecycle
    - Windows file handle cleanup works differently than Unix
    - The warning doesn't indicate a real issue - cleanup still works
    We filter this warning on Windows only to avoid test noise.
    """

    # Create marker files to track server lifecycle
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        startup_marker = f.name
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        cleanup_marker = f.name

    # Remove the files so we can detect when they're created
    Path(startup_marker).unlink()
    Path(cleanup_marker).unlink()

    # Create an MCP server that handles stdin closure gracefully
    server_code = textwrap.dedent(f"""
        import asyncio
        import sys
        from pathlib import Path
        from contextlib import asynccontextmanager
        from mcp.server.fastmcp import FastMCP
        
        STARTUP_MARKER = {escape_path_for_python(startup_marker)}
        CLEANUP_MARKER = {escape_path_for_python(cleanup_marker)}
        
        @asynccontextmanager
        async def lifespan(server):
            # Write startup marker
            Path(STARTUP_MARKER).write_text("started")
            try:
                yield {{"started": True}}
            finally:
                # This cleanup code runs when stdin closes, enabling graceful shutdown
                Path(CLEANUP_MARKER).write_text("cleaned up")
        
        mcp = FastMCP("test-server", lifespan=lifespan)
        
        @mcp.tool()
        def echo(text: str) -> str:
            return text
        
        if __name__ == "__main__":
            # The server should exit gracefully when stdin closes
            try:
                mcp.run()
            except Exception:
                # Server might get EOF or other errors when stdin closes
                pass
    """)

    # Write the server script to a temporary file
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".py") as f:
        server_script = f.name
        f.write(server_code)

    try:
        # This test manually manages the process to verify stdin-based shutdown
        # Start the server process
        process = await _create_platform_compatible_process(
            command=sys.executable, args=[server_script], env=None, errlog=sys.stderr, cwd=None
        )

        # Wait for server to start
        with anyio.move_on_after(10.0):
            while not Path(startup_marker).exists():
                await anyio.sleep(0.1)

        # Check if process is still running
        if hasattr(process, "returncode") and process.returncode is not None:
            pytest.fail(f"Server process exited with code {process.returncode}")

        assert Path(startup_marker).exists(), "Server startup marker not created"

        # Close stdin to signal shutdown
        if process.stdin:
            await process.stdin.aclose()

        # Wait for process to exit gracefully
        try:
            with anyio.fail_after(5.0):  # Increased from 2.0 to 5.0
                await process.wait()
        except TimeoutError:
            # If it doesn't exit after stdin close, terminate it
            process.terminate()
            await process.wait()

        # Check if cleanup ran
        with anyio.move_on_after(5.0):
            while not Path(cleanup_marker).exists():
                await anyio.sleep(0.1)

        # Verify the cleanup ran - stdin closure enables graceful shutdown
        assert Path(cleanup_marker).exists(), "Server cleanup marker not created - stdin-based shutdown failed"
        assert Path(cleanup_marker).read_text() == "cleaned up"

    finally:
        # Clean up files
        for path in [server_script, startup_marker, cleanup_marker]:
            try:
                Path(path).unlink()
            except FileNotFoundError:
                pass
