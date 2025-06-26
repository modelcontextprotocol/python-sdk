"""Test Windows-specific FallbackProcess functionality.

Why this test approach is necessary:
------------------------------------
Testing Windows process signal handling requires actual subprocess creation because:

1. SIGNAL HANDLING: We need to verify that CTRL_C_EVENT signals are properly sent and
   received. This cannot be mocked as it involves OS-level signal propagation between
   parent and child processes.

2. CLEANUP VERIFICATION: The core issue (#1027) is that cleanup code in lifespan context
   managers wasn't executing on Windows. We must verify that signal handlers actually run
   and that cleanup code executes before process termination.

3. WINDOWS-SPECIFIC BEHAVIOR: The FallbackProcess class exists specifically to work around
   Windows asyncio limitations. Testing it requires actual Windows subprocess creation to
   ensure the workarounds function correctly.

4. INTEGRATION TESTING: These tests verify the integration between:
   - FallbackProcess wrapper
   - Windows signal handling (CTRL_C_EVENT)
   - Asyncio file streams
   - Process cleanup behavior

Test Implementation:
-------------------
The tests create temporary Python scripts that:
1. Set up signal handlers for CTRL_C_EVENT
2. Write marker files to indicate execution state
3. Allow verification that cleanup ran before termination

This metaprogramming approach is used because:
- The codebase doesn't have a test fixtures directory pattern
- Inline `python -c` would be even less readable for complex scripts
- We need actual subprocess execution to test OS-level behavior
"""

import os
import signal
import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING or sys.platform == "win32":
    from mcp.client.stdio.win32 import create_windows_process


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific functionality")
class TestFallbackProcess:
    """Test suite for Windows FallbackProcess graceful shutdown."""

    @pytest.mark.anyio
    async def test_fallback_process_graceful_shutdown(self, tmp_path: Path):
        """Test that FallbackProcess sends CTRL_C_EVENT for graceful shutdown."""
        # Create a test script that writes a marker on cleanup
        test_script = tmp_path / "test_cleanup.py"
        marker_file = tmp_path / "cleanup_marker.txt"

        # Create a test script that handles CTRL_C_EVENT and writes a marker on cleanup
        test_script.write_text(
            textwrap.dedent(f"""
            import signal
            import time
            from pathlib import Path
            
            marker = Path(r"{marker_file}")
            marker.write_text("STARTED")
            
            def cleanup_handler(signum, frame):
                # This handler should be called when CTRL_C_EVENT is received
                marker.write_text("CLEANED_UP")
                exit(0)
            
            # Register CTRL_C_EVENT handler (SIGINT on Windows)
            signal.signal(signal.SIGINT, cleanup_handler)
            
            # Keep process alive waiting for signal
            while True:
                time.sleep(0.1)
        """).strip()
        )

        # Create process using FallbackProcess
        process = await create_windows_process(sys.executable, [str(test_script)], cwd=tmp_path)

        # Wait for process to start
        import asyncio

        await asyncio.sleep(0.5)

        # Verify process started
        assert marker_file.exists()
        assert marker_file.read_text() == "STARTED"

        # Exit context manager - should trigger CTRL_C_EVENT
        await process.__aexit__(None, None, None)

        # Check if cleanup ran
        await asyncio.sleep(0.5)

        # This is the critical test: cleanup should have executed
        assert marker_file.read_text() == "CLEANED_UP", "CTRL_C_EVENT cleanup did not execute - issue #1027 not fixed"

    @pytest.mark.anyio
    async def test_fallback_process_timeout_fallback(self, tmp_path: Path):
        """Test that FallbackProcess falls back to terminate() if CTRL_C_EVENT times out."""
        # Create a test script that ignores CTRL_C_EVENT
        test_script = tmp_path / "test_ignore_signal.py"
        marker_file = tmp_path / "status_marker.txt"

        # Create a test script that ignores CTRL_C_EVENT to test fallback behavior
        test_script.write_text(
            textwrap.dedent(f"""
            import signal
            import time
            from pathlib import Path
            
            marker = Path(r"{marker_file}")
            marker.write_text("STARTED")
            
            # Explicitly ignore CTRL_C_EVENT to test fallback to terminate()
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            
            # Keep process alive - should be forcefully terminated
            while True:
                time.sleep(0.1)
        """).strip()
        )

        # Create process
        process = await create_windows_process(sys.executable, [str(test_script)], cwd=tmp_path)

        # Wait for process to start
        import asyncio

        await asyncio.sleep(0.5)

        assert marker_file.exists()
        assert marker_file.read_text() == "STARTED"

        # Exit context manager - should try CTRL_C_EVENT, timeout, then terminate
        await process.__aexit__(None, None, None)

        # Process should be terminated even though it ignored CTRL_C_EVENT
        # Check that process is no longer running
        try:
            # This should raise because process is terminated
            os.kill(process.popen.pid, 0)
            pytest.fail("Process should have been terminated")
        except (ProcessLookupError, OSError):
            # Expected - process is terminated
            pass

    def test_ctrl_c_event_availability(self):
        """Test that CTRL_C_EVENT is available on Windows."""
        assert hasattr(signal, "CTRL_C_EVENT"), "CTRL_C_EVENT not available on this Windows system"

        # Verify it's the expected value (should be 0)
        assert signal.CTRL_C_EVENT == 0

    @pytest.mark.anyio
    async def test_fallback_process_with_stdio(self, tmp_path: Path):
        """Test that FallbackProcess properly wraps stdin/stdout streams."""
        # Create a simple echo script to test stdio stream wrapping
        echo_script = tmp_path / "echo.py"
        echo_script.write_text(
            textwrap.dedent("""
            import sys
            while True:
                line = sys.stdin.readline()
                if not line:
                    break
                sys.stdout.write(f"ECHO: {line}")
                sys.stdout.flush()
        """).strip()
        )

        # Create process
        process = await create_windows_process(sys.executable, [str(echo_script)], cwd=tmp_path)

        # Test async I/O
        assert process.stdin is not None
        assert process.stdout is not None

        # Write to stdin
        test_message = b"Hello Windows\\n"
        await process.stdin.send(test_message)

        # Read from stdout
        import asyncio

        response = await asyncio.wait_for(process.stdout.receive(1024), timeout=2.0)

        assert b"ECHO: Hello Windows" in response

        # Cleanup
        await process.__aexit__(None, None, None)
