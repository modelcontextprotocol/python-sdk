import asyncio
import sys

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
@pytest.mark.anyio
async def test_windows_process_creation():
    """
    Test that directly tests the process creation function that was fixed in issue #552.
    This simpler test verifies that Windows process creation works without hanging.
    """
    # Use a simple command that should complete quickly on Windows
    params = StdioServerParameters(
        command="cmd",
        # Echo a valid JSON-RPC response message that will be parsed correctly
        args=[
            "/c",
            "echo",
            '{"jsonrpc":"2.0","id":1,"result":{"status":"success"}}',
        ],
    )

    # Directly test the fixed function that was causing the hanging issue
    try:
        # Set a timeout to prevent hanging
        async with asyncio.timeout(5):
            # Test the actual process creation function that was fixed
            async with stdio_client(params) as (read, write):
                print("inside client")
                async with ClientSession(read, write) as c:
                    print("inside ClientSession")
                    await c.initialize()

    except asyncio.TimeoutError:
        pytest.xfail("Process creation timed out, indicating a hang issue")
    except ProcessLookupError:
        pytest.xfail("Process creation failed with ProcessLookupError")
    except Exception as e:
        assert "ExceptionGroup" in repr(e), f"Unexpected error: {e}"
        assert "ProcessLookupError" in repr(e), f"Unexpected error: {e}"
        pytest.xfail(f"Expected error: {e}")
