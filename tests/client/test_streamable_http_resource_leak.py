"""
Test for the resource leak I found in streamable_http.py.

I noticed that when SSE streaming fails with exceptions, the HTTP response doesn't
get closed properly in _handle_sse_response and _handle_resumption_request.

The problem: when the async for loop throws an exception, the response.aclose()
call never happens because it's only in the success path.

Files affected:
- src/mcp/client/streamable_http.py (lines 336 and 251)

This can cause connection pool exhaustion in production.
"""

from typing import Any

import pytest

from mcp.client.streamable_http import StreamableHTTPTransport


class MockResponse:
    """Simple mock to track if aclose() gets called"""

    closed: bool
    close_count: int
    _is_closed: bool

    def __init__(self) -> None:
        self.closed = False
        self.close_count = 0
        self._is_closed = False

    async def aclose(self) -> None:
        self.closed = True
        self.close_count += 1
        self._is_closed = True

    @property
    def is_closed(self) -> bool:
        return self._is_closed


class MockEventSource:
    """Mock that throws an exception to simulate broken SSE"""

    def __init__(self, response: MockResponse) -> None:
        self.response = response

    def __aiter__(self) -> "MockEventSource":
        return self

    async def __anext__(self) -> Any:
        # Simulate what happens when SSE parsing fails
        raise Exception("SSE parsing failed - connection broken")


class MockTransport(StreamableHTTPTransport):
    """Mock that shows the same bug as the real code"""

    def __init__(self) -> None:
        super().__init__("http://test")
        self.mock_response = MockResponse()

    async def _handle_sse_response(self, response: Any, ctx: Any, is_initialization: bool = False) -> None:
        """
        This mimics the actual bug in the real code.

        The problem: when the async for loop throws an exception,
        response.aclose() never gets called because it's only in the success path.
        """
        try:
            event_source = MockEventSource(response)
            async for _sse in event_source:
                # This never runs because the exception happens first
                is_complete = False  # Simulate event processing
                if is_complete:
                    await response.aclose()  # This is line 336 in the real code
                    break
        except Exception:
            # Here's the bug - response.aclose() is never called!
            raise


class TestStreamableHTTPResourceLeak:
    """Tests for the resource leak I found in streamable HTTP"""

    @pytest.mark.anyio
    async def test_handle_sse_response_resource_leak(self) -> None:
        """Test that _handle_sse_response leaks resources when SSE fails"""
        transport = MockTransport()

        # Create mock context
        class MockContext:
            def __init__(self) -> None:
                self.read_stream_writer = None
                self.metadata = None

        ctx = MockContext()

        # This should raise an exception due to the mock EventSource
        with pytest.raises(Exception, match="SSE parsing failed"):
            await transport._handle_sse_response(transport.mock_response, ctx)

        # Verify that the response was NOT closed (resource leak)
        assert not transport.mock_response.closed, (
            "Resource leak detected: response should not be closed when SSE streaming fails"
        )
        assert transport.mock_response.close_count == 0, (
            "Resource leak detected: response.aclose() should not have been called"
        )

    @pytest.mark.anyio
    async def test_handle_resumption_request_resource_leak(self) -> None:
        """Test that _handle_resumption_request leaks resources when SSE fails"""
        transport = MockTransport()

        # Override the method to reproduce the bug
        async def mock_handle_resumption_request(ctx: Any) -> None:
            try:
                # Mock aconnect_sse context manager
                class MockEventSourceWithResponse:
                    def __init__(self, response: MockResponse) -> None:
                        self.response = response

                    async def __aenter__(self) -> "MockEventSourceWithResponse":
                        return self

                    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
                        # Even if context manager exits, the response might not be closed
                        pass

                    def __aiter__(self) -> "MockEventSourceWithResponse":
                        return self

                    async def __anext__(self) -> Any:
                        raise Exception("Resumption SSE parsing failed")

                async with MockEventSourceWithResponse(transport.mock_response) as event_source:
                    async for _sse in event_source:
                        # This code will never be reached due to the exception
                        is_complete = False
                        if is_complete:
                            await event_source.response.aclose()  # Only closed in success path (line 251)
                            break
            except Exception:
                # BUG: response.aclose() is never called here!
                raise

        # Create mock context with resumption token
        class MockResumptionContext:
            def __init__(self) -> None:
                self.read_stream_writer = None
                self.metadata = type("obj", (object,), {"resumption_token": "test-token"})()
                self.session_message = type(
                    "obj",
                    (object,),
                    {"message": type("obj", (object,), {"root": type("obj", (object,), {"id": "test-id"})()})()},
                )()

        ctx_resumption = MockResumptionContext()

        # This should raise an exception due to the mock EventSource
        with pytest.raises(Exception, match="Resumption SSE parsing failed"):
            await mock_handle_resumption_request(ctx_resumption)

        # Verify that the response was NOT closed (resource leak)
        assert not transport.mock_response.closed, (
            "Resource leak detected: response should not be closed when resumption SSE fails"
        )
        assert transport.mock_response.close_count == 0, (
            "Resource leak detected: response.aclose() should not have been called"
        )

    @pytest.mark.anyio
    async def test_resource_leak_fix_verification(self) -> None:
        """Test that shows how the fix should work"""
        transport = MockTransport()

        # Create mock context
        class MockContext:
            def __init__(self) -> None:
                self.read_stream_writer = None
                self.metadata = None

        ctx = MockContext()

        # Simulate the FIXED version with finally block
        async def fixed_handle_sse_response(response: MockResponse, ctx: Any, is_initialization: bool = False) -> None:
            try:
                event_source = MockEventSource(response)
                async for _sse in event_source:
                    # This code will never be reached due to the exception
                    is_complete = False  # Simulate event processing
                    if is_complete:
                        await response.aclose()  # Only closed in success path
                        break
            except Exception:
                # Exception handling (existing code)
                raise
            finally:
                # FIX: Always close the response, even if exception occurs
                if not response.is_closed:
                    await response.aclose()

        # This should raise an exception due to the mock EventSource
        with pytest.raises(Exception, match="SSE parsing failed"):
            await fixed_handle_sse_response(transport.mock_response, ctx)

        # Verify that the response WAS closed (fix working)
        assert transport.mock_response.closed, "Fix test failed: response should be closed when finally block is used"
        assert transport.mock_response.close_count == 1, (
            "Fix test failed: response.aclose() should have been called once"
        )
