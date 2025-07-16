"""Test that cancelled requests don't cause double responses."""

import asyncio
from unittest.mock import MagicMock

import pytest

import mcp.types as types
from mcp.server.lowlevel.server import Server
from mcp.types import PingRequest, ServerResult


# Shared mock class
class MockRequestResponder:
    def __init__(self):
        self.request_id = "test-123"
        self._responded = False
        self.request_meta = {}
        self.message_metadata = None

    async def send(self, response):
        if self._responded:
            raise AssertionError(f"Request {self.request_id} already responded to")
        self._responded = True

    async def respond(self, response):
        await self.send(response)

    def cancel(self):
        """Simulate the cancel() method sending an error response."""
        asyncio.create_task(self.send(ServerResult(error=types.ErrorData(code=-32800, message="Request cancelled"))))


@pytest.mark.anyio
async def test_cancelled_request_no_double_response():
    """Verify server handles cancelled requests without double response."""

    # Create a server instance
    server = Server("test-server")

    # Track if multiple responses are attempted
    response_count = 0

    # Override the send method to track calls
    mock_message = MockRequestResponder()
    original_send = mock_message.send

    async def tracked_send(response):
        nonlocal response_count
        response_count += 1
        await original_send(response)

    mock_message.send = tracked_send

    # Create a slow handler that will be cancelled
    async def slow_handler(req):
        await asyncio.sleep(10)
        return types.ServerResult(types.EmptyResult())

    # Use PingRequest as it's a valid request type
    server.request_handlers[types.PingRequest] = slow_handler

    # Create mock message and session
    mock_req = PingRequest(method="ping", params={})
    mock_session = MagicMock()
    mock_context = None

    # Start the request
    handle_task = asyncio.create_task(
        server._handle_request(mock_message, mock_req, mock_session, mock_context, raise_exceptions=False)
    )

    # Give it time to start
    await asyncio.sleep(0.1)

    # Simulate cancellation
    mock_message.cancel()
    handle_task.cancel()

    # Wait for cancellation to propagate
    try:
        await handle_task
    except asyncio.CancelledError:
        pass

    # Give time for any duplicate response attempts
    await asyncio.sleep(0.1)

    # Should only have one response (from cancel())
    assert response_count == 1, f"Expected 1 response, got {response_count}"


@pytest.mark.anyio
async def test_server_remains_functional_after_cancel():
    """Verify server can handle new requests after a cancellation."""

    server = Server("test-server")

    # Add handlers
    async def slow_handler(req):
        await asyncio.sleep(5)
        return types.ServerResult(types.EmptyResult())

    async def fast_handler(req):
        return types.ServerResult(types.EmptyResult())

    # Override ping handler for our test
    server.request_handlers[types.PingRequest] = slow_handler

    # First request (will be cancelled)
    mock_message1 = MockRequestResponder()
    mock_req1 = PingRequest(method="ping", params={})

    handle_task = asyncio.create_task(
        server._handle_request(mock_message1, mock_req1, MagicMock(), None, raise_exceptions=False)
    )

    await asyncio.sleep(0.1)
    mock_message1.cancel()
    handle_task.cancel()

    try:
        await handle_task
    except asyncio.CancelledError:
        pass

    # Change handler to fast one
    server.request_handlers[types.PingRequest] = fast_handler

    # Second request (should work normally)
    mock_message2 = MockRequestResponder()
    mock_req2 = PingRequest(method="ping", params={})

    # This should complete successfully
    await server._handle_request(mock_message2, mock_req2, MagicMock(), None, raise_exceptions=False)

    # Server handled the second request successfully
    assert mock_message2._responded
