import asyncio
import sys

import pytest

from mcp import StdioServerParameters
from mcp.client.stdio import _create_platform_compatible_process


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
@pytest.mark.anyio
async def test_windows_process_creation():
    """
    Test that directly tests the process creation function that was fixed in issue #552.
    This simpler test verifies that Windows process creation works without hanging.
    """
    # Use a simple command that should complete quickly on Windows
    params = StdioServerParameters(
        command="cmd", args=["/c", "echo", "Test successful"]
    )

    # Directly test the fixed function that was causing the hanging issue
    process = None
    try:
        # Set a timeout to prevent hanging
        async with asyncio.timeout(3):
            # Test the actual process creation function that was fixed
            process = await _create_platform_compatible_process(
                command=params.command, args=params.args, env=None
            )

            # If we get here without hanging, the test is successful
            assert process is not None, "Process should be created successfully"

            # Read from stdout to verify process works
            if process.stdout:
                output = await process.stdout.receive()
                assert output, "Process should produce output"
    finally:
        # Clean up process
        if process:
            try:
                process.terminate()
            except Exception:
                # Ignore errors during cleanup
                pass
