#!/usr/bin/env python3
"""
Standalone reproduction script for issue #262: MCP Client Tool Call Hang

This script attempts to reproduce the issue where:
- await session.list_tools() works
- await session.call_tool() hangs indefinitely

Usage:
    python reproduce_262_standalone.py [--server-only] [--client-only PORT]

The script can run in three modes:
1. Full mode (default): Starts server and client in one process
2. Server mode: Just run the server for external client testing
3. Client mode: Connect to an existing server

Key observations from the original issue:
- Debugger stepping makes the issue disappear (timing-sensitive)
- Works on native Windows, fails on WSL Ubuntu
- Both stdio and SSE transports affected

See: https://github.com/modelcontextprotocol/python-sdk/issues/262
"""

import argparse
import asyncio
import sys
import textwrap

# Check if MCP is available
try:
    import mcp.types as types
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    print("ERROR: MCP SDK not installed. Run: pip install mcp")
    sys.exit(1)


# Server script that mimics a real MCP server
SERVER_SCRIPT = textwrap.dedent('''
    import json
    import sys
    import time

    def send_response(response):
        """Send a JSON-RPC response to stdout."""
        print(json.dumps(response), flush=True)

    def read_request():
        """Read a JSON-RPC request from stdin."""
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line)

    def main():
        print("Server started", file=sys.stderr, flush=True)

        while True:
            request = read_request()
            if request is None:
                print("Server: stdin closed, exiting", file=sys.stderr, flush=True)
                break

            method = request.get("method", "")
            request_id = request.get("id")
            print(f"Server received: {method}", file=sys.stderr, flush=True)

            if method == "initialize":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "test-server", "version": "1.0"}
                    }
                })
            elif method == "notifications/initialized":
                print("Server: Initialized notification received", file=sys.stderr, flush=True)
            elif method == "tools/list":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [{
                            "name": "query-api-infos",
                            "description": "Query API information",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "api_info_id": {"type": "string"}
                                }
                            }
                        }]
                    }
                })
                print("Server: Sent tools list", file=sys.stderr, flush=True)
            elif method == "tools/call":
                params = request.get("params", {})
                tool_name = params.get("name", "unknown")
                arguments = params.get("arguments", {})
                print(f"Server: Executing tool {tool_name} with args {arguments}", file=sys.stderr, flush=True)

                # Simulate some processing time (like the original issue)
                time.sleep(0.1)

                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Result for {tool_name}"}],
                        "isError": False
                    }
                })
                print(f"Server: Sent tool result", file=sys.stderr, flush=True)
            elif method == "ping":
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {}
                })
            else:
                print(f"Server: Unknown method {method}", file=sys.stderr, flush=True)
                send_response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                })

    if __name__ == "__main__":
        main()
''').strip()


async def handle_sampling_message(context, params: types.CreateMessageRequestParams):
    """Sampling callback as shown in the original issue."""
    return types.CreateMessageResult(
        role="assistant",
        content=types.TextContent(type="text", text="Hello from model"),
        model="gpt-3.5-turbo",
        stopReason="endTurn",
    )


async def run_test():
    """Main test that reproduces the issue scenario."""
    print("=" * 60)
    print("Issue #262 Reproduction Test")
    print("=" * 60)
    print()

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-c", SERVER_SCRIPT],
        env=None,
    )

    print(f"Starting server with: {sys.executable}")
    print()

    try:
        async with stdio_client(server_params) as (read, write):
            print("Connected to server")

            async with ClientSession(read, write, sampling_callback=handle_sampling_message) as session:
                print("Session created")

                # Initialize
                print("\n1. Initializing session...")
                result = await session.initialize()
                print(f"   Initialized with protocol version: {result.protocolVersion}")
                print(f"   Server: {result.serverInfo.name} v{result.serverInfo.version}")

                # List tools - this should work
                print("\n2. Listing tools...")
                tools = await session.list_tools()
                print(f"   Found {len(tools.tools)} tool(s):")
                for tool in tools.tools:
                    print(f"   - {tool.name}: {tool.description}")

                # Call tool - this is where the hang was reported
                print("\n3. Calling tool (this is where issue #262 hangs)...")
                print("   If this hangs, the issue is reproduced!")
                print("   Waiting...")

                # Use a timeout to detect the hang
                try:
                    import anyio

                    with anyio.fail_after(10):
                        result = await session.call_tool("query-api-infos", arguments={"api_info_id": "8768555"})
                        print(f"   Tool result: {result.content[0].text}")
                        print("\n" + "=" * 60)
                        print("SUCCESS: Tool call completed - issue NOT reproduced")
                        print("=" * 60)
                except TimeoutError:
                    print("\n" + "=" * 60)
                    print("TIMEOUT: Tool call hung - issue IS reproduced!")
                    print("=" * 60)
                    return False

        print("\n4. Session closed cleanly")
        return True

    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return False


async def run_multiple_iterations(n: int = 10):
    """Run the test multiple times to catch intermittent issues."""
    print(f"\nRunning {n} iterations to catch intermittent issues...")
    print()

    successes = 0
    failures = 0

    for i in range(n):
        print(f"\n{'=' * 60}")
        print(f"Iteration {i + 1}/{n}")
        print(f"{'=' * 60}")

        try:
            success = await run_test()
            if success:
                successes += 1
            else:
                failures += 1
        except Exception as e:
            print(f"Exception: {e}")
            failures += 1

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {successes} successes, {failures} failures")
    print(f"{'=' * 60}")

    if failures > 0:
        print("\nIssue #262 WAS reproduced in some iterations!")
    else:
        print("\nIssue #262 was NOT reproduced in any iteration.")


def main():
    parser = argparse.ArgumentParser(description="Reproduce issue #262")
    parser.add_argument("--iterations", "-n", type=int, default=1, help="Number of test iterations (default: 1)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")

    args = parser.parse_args()

    print(f"Python version: {sys.version}")
    print(f"Platform: {sys.platform}")
    print()

    if args.iterations > 1:
        asyncio.run(run_multiple_iterations(args.iterations))
    else:
        asyncio.run(run_test())


if __name__ == "__main__":
    main()
