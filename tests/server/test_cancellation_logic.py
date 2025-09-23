"""Tests for async operation cancellation logic."""

import pytest

import mcp.types as types
from mcp.server.lowlevel.async_operations import AsyncOperationManager
from mcp.server.lowlevel.server import Server
from mcp.shared.exceptions import McpError


class TestCancellationLogic:
    """Test cancellation logic for async operations."""

    def test_handle_cancelled_notification(self):
        """Test handling of cancelled notifications."""
        manager = AsyncOperationManager()
        server = Server("Test", async_operations=manager)

        # Create an operation
        operation = manager.create_operation("test_tool", {"arg": "value"}, "session1")

        # Track the operation with a request ID
        request_id = "req_123"
        server._request_to_operation[request_id] = operation.token

        # Handle cancellation
        server.handle_cancelled_notification(request_id)

        # Verify operation was cancelled
        cancelled_op = manager.get_operation(operation.token)
        assert cancelled_op is not None
        assert cancelled_op.status == "canceled"

        # Verify mapping was cleaned up
        assert request_id not in server._request_to_operation

    def test_cancelled_notification_handler(self):
        """Test the async cancelled notification handler."""
        manager = AsyncOperationManager()
        server = Server("Test", async_operations=manager)

        # Create an operation
        operation = manager.create_operation("test_tool", {"arg": "value"}, "session1")

        # Track the operation with a request ID
        request_id = "req_456"
        server._request_to_operation[request_id] = operation.token

        # Create cancelled notification
        notification = types.CancelledNotification(params=types.CancelledNotificationParams(requestId=request_id))

        # Handle the notification
        import asyncio

        asyncio.run(server._handle_cancelled_notification(notification))

        # Verify operation was cancelled
        cancelled_op = manager.get_operation(operation.token)
        assert cancelled_op is not None
        assert cancelled_op.status == "canceled"

    def test_validate_operation_token_cancelled(self):
        """Test that cancelled operations are rejected."""
        manager = AsyncOperationManager()
        server = Server("Test", async_operations=manager)

        # Create and cancel an operation
        operation = manager.create_operation("test_tool", {"arg": "value"}, "session1")
        manager.cancel_operation(operation.token)

        # Verify that accessing cancelled operation raises error
        with pytest.raises(McpError) as exc_info:
            server._validate_operation_token(operation.token)

        assert exc_info.value.error.code == -32602
        assert "cancelled" in exc_info.value.error.message.lower()

    def test_nonexistent_request_id_cancellation(self):
        """Test cancellation of non-existent request ID."""
        server = Server("Test")

        # Should not raise error for non-existent request ID
        server.handle_cancelled_notification("nonexistent_request")

        # Verify no operations were affected
        assert len(server._request_to_operation) == 0
