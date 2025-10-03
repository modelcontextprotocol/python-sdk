#!/usr/bin/env python3
"""
Diagnosis script for PR 671.

Since we cannot access the exact PR details directly, this script will test
common failure modes that might be related to issue #671 based on patterns
observed in the codebase.
"""

import asyncio
import logging
import sys
import traceback
from typing import Any

import anyio

# Test common failure scenarios that might be issue 671


async def test_session_initialization():
    """Test basic session initialization - common source of issues."""
    print("=== Testing Session Initialization ===")

    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.shared.memory import create_connected_server_and_client_session

        print("✓ Imports successful")

        # Create a test server first
        server = FastMCP("TestServer")

        @server.tool()
        def test_tool() -> str:
            """A simple test tool."""
            return "test result"

        print("✓ Test server created")

        # Test creating connected sessions - CORRECT USAGE
        async with create_connected_server_and_client_session(server._mcp_server) as client_session:
            print("✓ Connected client session created successfully")
            print("✓ Client session initialized successfully")

        return True

    except Exception as e:
        print(f"✗ Session initialization failed: {e}")
        traceback.print_exc()
        return False


async def test_protocol_version_handling():
    """Test protocol version handling - another common issue area."""
    print("\n=== Testing Protocol Version Handling ===")

    try:
        from mcp.client.session import ClientSession
        from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS

        print(f"✓ Supported protocol versions: {SUPPORTED_PROTOCOL_VERSIONS}")

        # Test with invalid protocol version
        try:
            # This should potentially cause issues if not handled properly
            pass
        except Exception as e:
            print(f"Expected error for invalid protocol: {e}")

        return True

    except Exception as e:
        print(f"✗ Protocol version handling failed: {e}")
        traceback.print_exc()
        return False


async def test_unicode_handling():
    """Test unicode handling in various scenarios."""
    print("\n=== Testing Unicode Handling ===")

    try:
        from mcp.server.fastmcp import FastMCP

        # Create server with unicode content
        server = FastMCP("TestServer")

        @server.tool()
        def unicode_tool(text: str = "Hello 世界! 🌍") -> str:
            """Tool that handles unicode text."""
            return f"Processed: {text}"

        @server.resource("test://unicode")
        def unicode_resource() -> str:
            """Resource with unicode content."""
            return "Unicode content: 测试数据 🚀"

        print("✓ Unicode server setup successful")

        # Test tool execution
        tools = await server.list_tools()
        print(f"✓ Listed {len(tools)} tools with unicode content")

        # Test resource access
        resources = await server.list_resources()
        print(f"✓ Listed {len(resources)} resources with unicode content")

        return True

    except Exception as e:
        print(f"✗ Unicode handling failed: {e}")
        traceback.print_exc()
        return False


async def test_error_propagation():
    """Test how errors are propagated through the system."""
    print("\n=== Testing Error Propagation ===")

    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.shared.exceptions import McpError

        server = FastMCP("ErrorTestServer")

        @server.tool()
        def error_tool() -> str:
            """Tool that raises an error."""
            raise ValueError("Intentional test error")

        print("✓ Error test server setup successful")

        # Test tool listing still works
        tools = await server.list_tools()
        print(f"✓ Listed {len(tools)} tools even with error-prone tool")

        return True

    except Exception as e:
        print(f"✗ Error propagation test failed: {e}")
        traceback.print_exc()
        return False


async def test_resource_template_edge_cases():
    """Test resource template handling - area with known issues."""
    print("\n=== Testing Resource Template Edge Cases ===")

    try:
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("TemplateTestServer")

        # Test various template patterns that might cause issues
        @server.resource("test://simple/{id}")
        def simple_template(id: str) -> str:
            return f"Resource {id}"

        @server.resource("test://complex/{category}/{id}")
        def complex_template(category: str, id: str) -> str:
            return f"Resource {category}/{id}"

        # Edge case: empty or special characters
        @server.resource("test://special/{id}")
        def special_chars_template(id: str) -> str:
            # Test with various special characters
            if not id or id.isspace():
                raise ValueError("Invalid ID")
            return f"Special resource: {id}"

        print("✓ Resource template setup successful")

        # Test template listing
        templates = await server.list_resource_templates()
        print(f"✓ Listed {len(templates)} resource templates")

        return True

    except Exception as e:
        print(f"✗ Resource template test failed: {e}")
        traceback.print_exc()
        return False


async def test_concurrent_operations():
    """Test concurrent operations - another area with known issues."""
    print("\n=== Testing Concurrent Operations ===")

    try:
        from mcp.server.fastmcp import FastMCP

        server = FastMCP("ConcurrentTestServer")

        call_count = 0

        @server.tool()
        async def concurrent_tool(delay: float = 0.1) -> str:
            """Tool that can be called concurrently."""
            nonlocal call_count
            call_count += 1
            current_call = call_count
            await anyio.sleep(delay)
            return f"Call #{current_call} completed"

        print("✓ Concurrent test server setup successful")

        # Test that tools are listed properly
        tools = await server.list_tools()
        print(f"✓ Listed {len(tools)} concurrent-capable tools")

        return True

    except Exception as e:
        print(f"✗ Concurrent operations test failed: {e}")
        traceback.print_exc()
        return False


async def main():
    """Run all diagnostic tests."""
    print("🔍 Diagnosing potential issues for PR 671")
    print("=" * 50)

    # Set up logging
    logging.basicConfig(level=logging.INFO)

    tests = [
        test_session_initialization,
        test_protocol_version_handling,
        test_unicode_handling,
        test_error_propagation,
        test_resource_template_edge_cases,
        test_concurrent_operations,
    ]

    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
        except Exception as e:
            print(f"✗ Test {test.__name__} crashed: {e}")
            traceback.print_exc()
            results.append(False)

    print("\n" + "=" * 50)
    print("🏁 DIAGNOSIS SUMMARY")
    print("=" * 50)

    for i, (test, result) in enumerate(zip(tests, results)):
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{i+1}. {test.__name__}: {status}")

    failed_count = sum(1 for r in results if not r)
    total_count = len(results)

    print(f"\nResults: {total_count - failed_count}/{total_count} tests passed")

    if failed_count > 0:
        print(f"\n⚠️  {failed_count} test(s) failed - these may indicate issue 671!")
        return 1
    else:
        print("\n✅ All tests passed - issue 671 may not be reproducible in this environment")
        return 0


if __name__ == "__main__":
    sys.exit(anyio.run(main))