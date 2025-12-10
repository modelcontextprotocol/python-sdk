#!/usr/bin/env python3
"""
Simple MCP client for reproducing issue #262.

This client connects to server_262.py and demonstrates the race condition
that causes call_tool() to hang.

USAGE:

  Normal run (should work):
    python client_262.py

  Reproduce the bug with GUARANTEED hang (use 'forever'):
    MCP_DEBUG_RACE_DELAY_STDIO=forever python client_262.py

  Or with a timed delay (may or may not hang depending on timing):
    MCP_DEBUG_RACE_DELAY_STDIO=0.5 python client_262.py

  You can also delay the session receive loop:
    MCP_DEBUG_RACE_DELAY_SESSION=forever python client_262.py

  Or both for maximum effect:
    MCP_DEBUG_RACE_DELAY_STDIO=forever MCP_DEBUG_RACE_DELAY_SESSION=forever python client_262.py

EXPLANATION:

The bug is caused by a race condition in the MCP client:

1. stdio_client creates zero-capacity memory streams (capacity=0)
2. stdio_client starts stdin_writer task with start_soon() (not awaited)
3. When client calls send_request(), it sends to the write_stream
4. If stdin_writer hasn't reached its receive loop yet, send() blocks forever

The environment variables inject delays at the start of the background tasks,
widening the race window to make the bug reliably reproducible.

See: https://github.com/modelcontextprotocol/python-sdk/issues/262
"""

import os
import sys

import anyio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    print("=" * 70)
    print("Issue #262 Reproduction Client")
    print("=" * 70)
    print()

    # Check if debug delays are enabled
    stdio_delay = os.environ.get("MCP_DEBUG_RACE_DELAY_STDIO")
    session_delay = os.environ.get("MCP_DEBUG_RACE_DELAY_SESSION")

    if stdio_delay or session_delay:
        print("DEBUG DELAYS ENABLED:")
        if stdio_delay:
            print(f"  MCP_DEBUG_RACE_DELAY_STDIO = {stdio_delay}s")
        if session_delay:
            print(f"  MCP_DEBUG_RACE_DELAY_SESSION = {session_delay}s")
        print()
        print("This should cause a hang/timeout due to the race condition!")
        print()
    else:
        print("No debug delays - this should work normally.")
        print()
        print("To reproduce the bug, run with:")
        print("  MCP_DEBUG_RACE_DELAY_STDIO=forever python client_262.py")
        print()

    # Server parameters - run server_262.py
    script_dir = os.path.dirname(os.path.abspath(__file__))
    server_script = os.path.join(script_dir, "server_262.py")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-u", server_script],  # -u for unbuffered output
    )

    timeout = 5.0  # 5 second timeout to detect hangs
    print(f"Connecting to server (timeout: {timeout}s)...")
    print()

    try:
        with anyio.fail_after(timeout):
            async with stdio_client(params) as (read_stream, write_stream):
                print("[OK] Connected to server via stdio")

                async with ClientSession(read_stream, write_stream) as session:
                    print("[OK] ClientSession created")

                    # Initialize
                    print("Calling session.initialize()...")
                    init_result = await session.initialize()
                    print(f"[OK] Initialized: {init_result.serverInfo.name}")

                    # List tools
                    print("Calling session.list_tools()...")
                    tools = await session.list_tools()
                    print(f"[OK] Listed {len(tools.tools)} tools: {[t.name for t in tools.tools]}")

                    # Call tool - this is where issue #262 hangs!
                    print("Calling session.call_tool('greet', {'name': 'Issue 262'})...")
                    result = await session.call_tool("greet", arguments={"name": "Issue 262"})
                    print(f"[OK] Tool result: {result.content[0].text}")

        print()
        print("=" * 70)
        print("SUCCESS! All operations completed without hanging.")
        print("=" * 70)

    except TimeoutError:
        print()
        print("=" * 70)
        print("TIMEOUT! The client hung - race condition reproduced!")
        print("=" * 70)
        print()
        print("This is issue #262: The race condition caused a deadlock.")
        print()
        print("Root cause:")
        print("  - Zero-capacity streams require sender and receiver to rendezvous")
        print("  - Background tasks (stdin_writer) are started with start_soon()")
        print("  - If send_request() runs before stdin_writer is ready, it blocks forever")
        print()
        print("The injected delays widen this race window to make it reproducible.")
        sys.exit(1)

    except Exception as e:
        print()
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    anyio.run(main)
