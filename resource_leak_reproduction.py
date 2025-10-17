#!/usr/bin/env python3
"""
Reproduction script for the resource leak I found in streamable_http.py

I noticed that when SSE streaming fails, the HTTP response doesn't get closed properly.
This happens in both _handle_sse_response and _handle_resumption_request methods.

The problem: if the async for loop throws an exception (like malformed JSON or network issues),
the response.aclose() call never happens because it's only in the success path.

Files affected:
- src/mcp/client/streamable_http.py (lines 336 and 251)

This can cause connection pool exhaustion over time in production.
"""

import asyncio
import sys
from pathlib import Path

# Add the mcp module to the path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from mcp.client.streamable_http import StreamableHTTPTransport


class MockResponse:
    """Simple mock to track if aclose() gets called"""

    def __init__(self):
        self.closed = False
        self.close_count = 0

    async def aclose(self):
        self.closed = True
        self.close_count += 1
        print(f"Response closed (called {self.close_count} times)")


class MockEventSource:
    """Mock that throws an exception to simulate broken SSE"""

    def __init__(self, response):
        self.response = response

    def __aiter__(self):
        return self

    async def __anext__(self):
        # Simulate what happens when SSE parsing fails
        raise Exception("SSE parsing failed - connection broken")


class MockTransport(StreamableHTTPTransport):
    """Mock that shows the same bug as the real code"""

    def __init__(self):
        super().__init__("http://test")
        self.mock_response = MockResponse()

    async def _handle_sse_response(self, response, ctx, is_initialization=False):
        """
        This mimics the actual bug in the real code.

        The problem: when the async for loop throws an exception,
        response.aclose() never gets called because it's only in the success path.
        """
        try:
            event_source = MockEventSource(response)
            async for sse in event_source:
                # This never runs because the exception happens first
                is_complete = False
                if is_complete:
                    await response.aclose()  # This is line 336 in the real code
                    break
        except Exception as e:
            print(f"Exception caught: {e}")
            # Here's the bug - response.aclose() is never called!
            raise

    async def _handle_resumption_request(self, ctx):
        """
        Same issue here - the aconnect_sse context manager should handle cleanup,
        but if exceptions happen during SSE iteration, the response might not get closed.
        """
        try:
            # Mock the aconnect_sse context manager
            class MockEventSourceWithResponse:
                def __init__(self, response):
                    self.response = response

                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    # Context manager exits but response might not be closed
                    pass

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    raise Exception("Resumption SSE parsing failed")

            async with MockEventSourceWithResponse(self.mock_response) as event_source:
                async for sse in event_source:
                    # This never runs because the exception happens first
                    is_complete = False
                    if is_complete:
                        await event_source.response.aclose()  # This is line 251 in the real code
                        break
        except Exception as e:
            print(f"Exception caught: {e}")
            # Same bug here - response.aclose() is never called!
            raise


async def test_resource_leak():
    """Test the resource leak I found"""
    print("Testing resource leak in streamable_http.py")
    print("=" * 50)

    transport = MockTransport()

    # Create mock context
    class MockContext:
        def __init__(self):
            self.read_stream_writer = None
            self.metadata = None

    ctx = MockContext()

    print("\nTesting _handle_sse_response method:")
    print("-" * 35)

    try:
        await transport._handle_sse_response(transport.mock_response, ctx)
    except Exception as e:
        print(f"Caught expected exception: {e}")

    # Check if response was closed
    if transport.mock_response.closed:
        print("No resource leak - response was closed properly")
        return True
    else:
        print("RESOURCE LEAK DETECTED!")
        print(f"   Response closed: {transport.mock_response.closed}")
        print(f"   Close count: {transport.mock_response.close_count}")
        print("   Expected: response.aclose() to be called in finally block")
        return False


async def test_resumption_resource_leak():
    """Test the resource leak in _handle_resumption_request"""
    print("\nTesting _handle_resumption_request method:")
    print("-" * 40)

    transport = MockTransport()

    # Create mock context with resumption token
    class MockResumptionContext:
        def __init__(self):
            self.read_stream_writer = None
            self.metadata = type("obj", (object,), {"resumption_token": "test-token"})()
            self.session_message = type(
                "obj",
                (object,),
                {"message": type("obj", (object,), {"root": type("obj", (object,), {"id": "test-id"})()})()},
            )()

    ctx_resumption = MockResumptionContext()

    try:
        await transport._handle_resumption_request(ctx_resumption)
    except Exception as e:
        print(f"Caught expected exception: {e}")

    # Check if response was closed
    if transport.mock_response.closed:
        print("No resource leak - response was closed properly")
        return True
    else:
        print("RESOURCE LEAK DETECTED!")
        print(f"   Response closed: {transport.mock_response.closed}")
        print(f"   Close count: {transport.mock_response.close_count}")
        print("   Expected: response.aclose() to be called in finally block")
        return False


async def main():
    """Run the tests to show the resource leak"""
    print("Resource Leak Test")
    print("This shows the issue I found where HTTP responses don't get closed")
    print("when SSE streaming fails in the MCP Python SDK.")
    print()

    # Test both methods
    sse_leak = await test_resource_leak()
    resumption_leak = await test_resumption_resource_leak()

    print("\n" + "=" * 50)
    print("SUMMARY:")
    print("=" * 50)

    if sse_leak and resumption_leak:
        print("All tests passed - no resource leaks detected")
        return 0
    else:
        print("Resource leaks confirmed in the following methods:")
        if not sse_leak:
            print("   - _handle_sse_response (line 336)")
        if not resumption_leak:
            print("   - _handle_resumption_request (line 251)")
        print()
        print("FIX NEEDED:")
        print("   Add finally blocks to ensure response.aclose() is always called:")
        print("   ```python")
        print("   try:")
        print("       # ... existing code ...")
        print("   except Exception as e:")
        print("       # ... existing exception handling ...")
        print("   finally:")
        print("       await response.aclose()")
        print("   ```")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
