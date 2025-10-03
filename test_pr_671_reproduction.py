#!/usr/bin/env python3
"""
Reproduction and fix for PR 671: create_connected_server_and_client_session API confusion

This test demonstrates the issue and the correct usage of the create_connected_server_and_client_session function.

ISSUE IDENTIFIED:
The create_connected_server_and_client_session function is commonly misused due to its signature:
- It requires a 'server' parameter as the first argument
- It yields a ClientSession (not a tuple)
- It's an async context manager

COMMON MISTAKES:
1. Calling it without arguments: create_connected_server_and_client_session()
2. Expecting it to return multiple values: server_session, client_session = await create_connected_server_and_client_session()
3. Not using it as an async context manager
"""

import asyncio
import sys

import anyio


async def demonstrate_incorrect_usage():
    """Show what DOESN'T work - this reproduces the issue."""
    print("=== DEMONSTRATING INCORRECT USAGE (reproduces PR 671 issue) ===")

    try:
        from mcp.shared.memory import create_connected_server_and_client_session

        # MISTAKE 1: Missing required server parameter
        print("❌ Attempting to call without server parameter...")
        try:
            # This will fail with: create_connected_server_and_client_session() missing 1 required positional argument: 'server'
            async with create_connected_server_and_client_session() as client:
                pass
        except TypeError as e:
            print(f"   ERROR: {e}")
            return "missing_server_argument"

        # MISTAKE 2: Treating it like it returns multiple values
        print("❌ Attempting to unpack multiple return values...")
        try:
            from mcp.server.fastmcp import FastMCP

            server = FastMCP("TestServer")

            @server.tool()
            def test_tool() -> str:
                return "test"

            # This would fail because the function only yields one value (ClientSession)
            async with create_connected_server_and_client_session(server._mcp_server) as (server_session, client_session):
                pass
        except ValueError as e:
            print(f"   ERROR: {e}")
            return "unpacking_error"

    except Exception as e:
        print(f"   UNEXPECTED ERROR: {e}")
        return "unexpected_error"

    return None


async def demonstrate_correct_usage():
    """Show what DOES work - the correct usage."""
    print("\n=== DEMONSTRATING CORRECT USAGE (fixes PR 671 issue) ===")

    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.shared.memory import create_connected_server_and_client_session

        # Create a proper server first
        server = FastMCP("CorrectUsageServer")

        @server.tool()
        def example_tool(message: str = "Hello") -> str:
            """An example tool for testing."""
            return f"Tool response: {message}"

        @server.resource("test://example")
        def example_resource() -> str:
            """An example resource for testing."""
            return "Example resource content"

        print("✅ Server created successfully")

        # CORRECT: Pass the server and use as async context manager yielding one value
        async with create_connected_server_and_client_session(server._mcp_server) as client_session:
            print("✅ Client session created successfully")

            # Test basic functionality
            tools_result = await client_session.list_tools()
            tools = tools_result.tools if hasattr(tools_result, 'tools') else []
            print(f"✅ Listed {len(tools)} tools: {[tool.name for tool in tools]}")

            resources_result = await client_session.list_resources()
            resources = resources_result.resources if hasattr(resources_result, 'resources') else []
            print(f"✅ Listed {len(resources)} resources")

            # Test calling a tool
            result = await client_session.call_tool("example_tool", {"message": "Test from PR 671 fix"})
            print(f"✅ Tool call result: {result.content[0].text if result.content else 'No content'}")

        print("✅ Client session closed cleanly")
        return True

    except Exception as e:
        print(f"❌ Correct usage failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Main function to demonstrate the issue and fix."""
    print("🔍 PR 671 REPRODUCTION AND FIX DEMONSTRATION")
    print("=" * 60)

    # First, show what goes wrong
    error_type = await demonstrate_incorrect_usage()

    # Then, show the correct way
    success = await demonstrate_correct_usage()

    print("\n" + "=" * 60)
    print("🏁 SUMMARY")
    print("=" * 60)

    if error_type == "missing_server_argument":
        print("✅ CONFIRMED: PR 671 issue reproduced!")
        print("   Issue: create_connected_server_and_client_session() called without required 'server' parameter")
    elif error_type == "unpacking_error":
        print("✅ CONFIRMED: Related unpacking issue found!")
        print("   Issue: Function yields single ClientSession, not multiple values")
    elif error_type:
        print(f"⚠️  Different error found: {error_type}")

    if success:
        print("✅ SOLUTION: Correct usage demonstrated successfully")
        print("   Fix: Pass server parameter and use as async context manager with single return value")
    else:
        print("❌ Solution failed - may need further investigation")

    print("\n📚 CORRECT API USAGE:")
    print("   async with create_connected_server_and_client_session(your_server) as client:")
    print("       # Use client here")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(anyio.run(main))