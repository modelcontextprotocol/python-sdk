"""Test for issue #552: stdio_client hangs on Windows."""

import sys
from textwrap import dedent

import anyio
import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
@pytest.mark.anyio
async def test_windows_stdio_client_with_session():
    """
    Test the exact scenario from issue #552: Using ClientSession with stdio_client.

    This reproduces the original bug report where stdio_client hangs on Windows 11
    when used with ClientSession.
    """
    # Create a minimal MCP server that responds to initialization
    server_script = dedent("""
        import json
        import sys

        # Read initialization request
        line = sys.stdin.readline()

        # Send initialization response
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "1.0",
                "capabilities": {},
                "serverInfo": {"name": "test-server", "version": "1.0"}
            }
        }
        print(json.dumps(response))
        sys.stdout.flush()

        # Exit after a short delay
        import time
        time.sleep(0.1)
        sys.exit(0)
    """).strip()

    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", server_script],
    )

    # This is the exact pattern from the bug report
    with anyio.fail_after(10):
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                # Should exit ClientSession without hanging
            # Should exit stdio_client without hanging
        except Exception:
            # Connection errors are expected when process exits
            pass
