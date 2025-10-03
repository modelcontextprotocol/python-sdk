"""Test async operations integration in lowlevel Server."""

import time
from typing import cast

import pytest

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.shared.async_operations import ServerAsyncOperationManager
from mcp.shared.exceptions import McpError


class TestLowlevelServerAsyncOperations:
    """Test lowlevel Server async operations integration."""

    @pytest.mark.anyio
    async def test_check_async_status_invalid_token(self):
        """Test get_operation_status handler with invalid token."""
        manager = ServerAsyncOperationManager()
        server = Server("Test", async_operations=manager)

        # Register the handler
        @server.get_operation_status()
        async def check_status_handler(token: str) -> types.GetOperationStatusResult:
            # This function is not actually called due to built-in logic
            return types.GetOperationStatusResult(status="unknown")

        # Test invalid token
        invalid_request = types.GetOperationStatusRequest(params=types.GetOperationStatusParams(token="invalid_token"))

        handler = server.request_handlers[types.GetOperationStatusRequest]

        with pytest.raises(McpError) as exc_info:
            await handler(invalid_request)

        assert exc_info.value.error.code == -32602
        assert exc_info.value.error.message == "Invalid token"

    @pytest.mark.anyio
    async def test_check_async_status_expired_token(self):
        """Test get_operation_status handler with expired token."""
        manager = ServerAsyncOperationManager()
        server = Server("Test", async_operations=manager)

        @server.get_operation_status()
        async def check_status_handler(token: str) -> types.GetOperationStatusResult:
            return types.GetOperationStatusResult(status="unknown")

        # Create and complete operation with short keepAlive
        operation = manager.create_operation("test_tool", {}, keep_alive=1, session_id="session1")
        manager.complete_operation(operation.token, types.CallToolResult(content=[]))

        # Make it expired
        operation.resolved_at = time.time() - 2

        expired_request = types.GetOperationStatusRequest(params=types.GetOperationStatusParams(token=operation.token))

        handler = server.request_handlers[types.GetOperationStatusRequest]

        with pytest.raises(McpError) as exc_info:
            await handler(expired_request)

        assert exc_info.value.error.code == -32602
        assert exc_info.value.error.message == "Token expired"

    @pytest.mark.anyio
    async def test_check_async_status_valid_operation(self):
        """Test get_operation_status handler with valid operation."""
        manager = ServerAsyncOperationManager()
        server = Server("Test", async_operations=manager)

        @server.get_operation_status()
        async def check_status_handler(token: str) -> types.GetOperationStatusResult:
            return types.GetOperationStatusResult(status="unknown")

        # Create valid operation
        operation = manager.create_operation("test_tool", {}, session_id="session1")
        manager.mark_working(operation.token)

        valid_request = types.GetOperationStatusRequest(params=types.GetOperationStatusParams(token=operation.token))

        handler = server.request_handlers[types.GetOperationStatusRequest]

        result = await handler(valid_request)

        assert isinstance(result, types.ServerResult)
        status_result = cast(types.GetOperationStatusResult, result.root)
        assert status_result.status == "working"
        assert status_result.error is None

    @pytest.mark.anyio
    async def test_check_async_status_failed_operation(self):
        """Test get_operation_status handler with failed operation."""
        manager = ServerAsyncOperationManager()
        server = Server("Test", async_operations=manager)

        @server.get_operation_status()
        async def check_status_handler(token: str) -> types.GetOperationStatusResult:
            return types.GetOperationStatusResult(status="unknown")

        # Create and fail operation
        operation = manager.create_operation("test_tool", {}, session_id="session1")
        manager.fail_operation(operation.token, "Something went wrong")

        failed_request = types.GetOperationStatusRequest(params=types.GetOperationStatusParams(token=operation.token))

        handler = server.request_handlers[types.GetOperationStatusRequest]

        result = await handler(failed_request)

        assert isinstance(result, types.ServerResult)
        status_result = cast(types.GetOperationStatusResult, result.root)
        assert status_result.status == "failed"
        assert status_result.error == "Something went wrong"

    @pytest.mark.anyio
    async def test_get_async_result_invalid_token(self):
        """Test get_operation_result handler with invalid token."""
        manager = ServerAsyncOperationManager()
        server = Server("Test", async_operations=manager)

        @server.get_operation_result()
        async def get_result_handler(token: str) -> types.GetOperationPayloadResult:
            return types.GetOperationPayloadResult(result=types.CallToolResult(content=[]))

        invalid_request = types.GetOperationPayloadRequest(
            params=types.GetOperationPayloadParams(token="invalid_token")
        )

        handler = server.request_handlers[types.GetOperationPayloadRequest]

        with pytest.raises(McpError) as exc_info:
            await handler(invalid_request)

        assert exc_info.value.error.code == -32602
        assert exc_info.value.error.message == "Invalid token"

    @pytest.mark.anyio
    async def test_get_async_result_expired_token(self):
        """Test get_operation_result handler with expired token."""
        manager = ServerAsyncOperationManager()
        server = Server("Test", async_operations=manager)

        @server.get_operation_result()
        async def get_result_handler(token: str) -> types.GetOperationPayloadResult:
            return types.GetOperationPayloadResult(result=types.CallToolResult(content=[]))

        # Create and complete operation with short keepAlive
        operation = manager.create_operation("test_tool", {}, keep_alive=1, session_id="session1")
        manager.complete_operation(operation.token, types.CallToolResult(content=[]))

        # Make it expired
        operation.resolved_at = time.time() - 2

        expired_request = types.GetOperationPayloadRequest(
            params=types.GetOperationPayloadParams(token=operation.token)
        )

        handler = server.request_handlers[types.GetOperationPayloadRequest]

        with pytest.raises(McpError) as exc_info:
            await handler(expired_request)

        assert exc_info.value.error.code == -32602
        assert exc_info.value.error.message == "Token expired"

    @pytest.mark.anyio
    async def test_get_async_result_not_completed(self):
        """Test get_operation_result handler with non-completed operation."""
        manager = ServerAsyncOperationManager()
        server = Server("Test", async_operations=manager)

        @server.get_operation_result()
        async def get_result_handler(token: str) -> types.GetOperationPayloadResult:
            return types.GetOperationPayloadResult(result=types.CallToolResult(content=[]))

        # Create operation that's still working
        operation = manager.create_operation("test_tool", {}, session_id="session1")
        manager.mark_working(operation.token)

        working_request = types.GetOperationPayloadRequest(
            params=types.GetOperationPayloadParams(token=operation.token)
        )

        handler = server.request_handlers[types.GetOperationPayloadRequest]

        with pytest.raises(McpError) as exc_info:
            await handler(working_request)

        assert exc_info.value.error.code == -32600
        assert exc_info.value.error.message == "Operation not completed (status: working)"

    @pytest.mark.anyio
    async def test_get_async_result_completed_with_result(self):
        """Test get_operation_result handler with completed operation."""
        manager = ServerAsyncOperationManager()
        server = Server("Test", async_operations=manager)

        @server.get_operation_result()
        async def get_result_handler(token: str) -> types.GetOperationPayloadResult:
            return types.GetOperationPayloadResult(result=types.CallToolResult(content=[]))

        # Create and complete operation with result
        operation = manager.create_operation("test_tool", {}, session_id="session1")
        result = types.CallToolResult(content=[types.TextContent(type="text", text="success")])
        manager.complete_operation(operation.token, result)

        completed_request = types.GetOperationPayloadRequest(
            params=types.GetOperationPayloadParams(token=operation.token)
        )

        handler = server.request_handlers[types.GetOperationPayloadRequest]

        response = await handler(completed_request)

        assert isinstance(response, types.ServerResult)
        payload_result = cast(types.GetOperationPayloadResult, response.root)
        assert payload_result.result == result


class TestCancellationLogic:
    """Test cancellation logic for async operations."""

    @pytest.mark.anyio
    async def test_handle_cancelled_notification(self):
        """Test handling of cancelled notifications."""
        manager = ServerAsyncOperationManager()
        server = Server("Test", async_operations=manager)

        # Create an operation
        operation = manager.create_operation("test_tool", {"arg": "value"}, session_id="session1")

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

    @pytest.mark.anyio
    async def test_cancelled_notification_handler(self):
        """Test the async cancelled notification handler."""
        manager = ServerAsyncOperationManager()
        server = Server("Test", async_operations=manager)

        # Create an operation
        operation = manager.create_operation("test_tool", {"arg": "value"}, session_id="session1")

        # Track the operation with a request ID
        request_id = "req_456"
        server._request_to_operation[request_id] = operation.token

        # Create cancelled notification
        notification = types.CancelledNotification(params=types.CancelledNotificationParams(requestId=request_id))

        await server._handle_cancelled_notification(notification)

        # Verify operation was cancelled
        cancelled_op = manager.get_operation(operation.token)
        assert cancelled_op is not None
        assert cancelled_op.status == "canceled"

    @pytest.mark.anyio
    async def test_validate_operation_token_cancelled(self):
        """Test that cancelled operations are rejected."""
        manager = ServerAsyncOperationManager()
        server = Server("Test", async_operations=manager)

        # Create and cancel an operation
        operation = manager.create_operation("test_tool", {"arg": "value"}, session_id="session1")
        manager.cancel_operation(operation.token)

        # Verify that accessing cancelled operation raises error
        with pytest.raises(McpError) as exc_info:
            server._validate_operation_token(operation.token)

        assert exc_info.value.error.code == -32602
        assert "cancelled" in exc_info.value.error.message.lower()

    @pytest.mark.anyio
    async def test_nonexistent_request_id_cancellation(self):
        """Test cancellation of non-existent request ID."""
        server = Server("Test")

        # Should not raise error for non-existent request ID
        server.handle_cancelled_notification("nonexistent_request")

        # Verify no operations were affected
        assert len(server._request_to_operation) == 0


class TestInputRequiredBehavior:
    """Test input_required status handling for async operations."""

    @pytest.mark.anyio
    async def test_mark_input_required(self):
        """Test marking operation as requiring input."""
        manager = ServerAsyncOperationManager()

        # Create operation in submitted state
        operation = manager.create_operation("test_tool", {"arg": "value"}, session_id="session1")
        assert operation.status == "submitted"

        # Mark as input required
        result = manager.mark_input_required(operation.token)
        assert result is True

        # Verify status changed
        updated_op = manager.get_operation(operation.token)
        assert updated_op is not None
        assert updated_op.status == "input_required"

    @pytest.mark.anyio
    async def test_mark_input_required_from_working(self):
        """Test marking working operation as requiring input."""
        manager = ServerAsyncOperationManager()

        # Create and mark as working
        operation = manager.create_operation("test_tool", {"arg": "value"}, session_id="session1")
        manager.mark_working(operation.token)
        assert operation.status == "working"

        # Mark as input required
        result = manager.mark_input_required(operation.token)
        assert result is True
        assert operation.status == "input_required"

    @pytest.mark.anyio
    async def test_mark_input_required_invalid_states(self):
        """Test that input_required can only be set from valid states."""
        manager = ServerAsyncOperationManager()

        # Test from completed state
        operation = manager.create_operation("test_tool", {"arg": "value"}, session_id="session1")
        manager.complete_operation(operation.token, types.CallToolResult(content=[]))

        result = manager.mark_input_required(operation.token)
        assert result is False
        assert operation.status == "completed"

    @pytest.mark.anyio
    async def test_mark_input_completed(self):
        """Test marking input as completed."""
        manager = ServerAsyncOperationManager()

        # Create operation and mark as input required
        operation = manager.create_operation("test_tool", {"arg": "value"}, session_id="session1")
        manager.mark_input_required(operation.token)
        assert operation.status == "input_required"

        # Mark input as completed
        result = manager.mark_input_completed(operation.token)
        assert result is True
        assert operation.status == "working"

    @pytest.mark.anyio
    async def test_mark_input_completed_invalid_state(self):
        """Test that input can only be completed from input_required state."""
        manager = ServerAsyncOperationManager()

        # Create operation in submitted state
        operation = manager.create_operation("test_tool", {"arg": "value"}, session_id="session1")
        assert operation.status == "submitted"

        # Try to mark input completed from wrong state
        result = manager.mark_input_completed(operation.token)
        assert result is False
        assert operation.status == "submitted"

    @pytest.mark.anyio
    async def test_nonexistent_token_operations(self):
        """Test input_required operations on nonexistent tokens."""
        manager = ServerAsyncOperationManager()

        # Test with fake token
        assert manager.mark_input_required("fake_token") is False
        assert manager.mark_input_completed("fake_token") is False

    @pytest.mark.anyio
    async def test_server_send_request_for_operation(self):
        """Test server method for sending requests with operation tokens."""
        manager = ServerAsyncOperationManager()
        server = Server("Test", async_operations=manager)

        # Create operation
        operation = manager.create_operation("test_tool", {"arg": "value"}, session_id="session1")
        manager.mark_working(operation.token)

        # Create a mock request
        request = types.ServerRequest(
            types.CreateMessageRequest(
                params=types.CreateMessageRequestParams(
                    messages=[types.SamplingMessage(role="user", content=types.TextContent(type="text", text="test"))],
                    maxTokens=100,
                )
            )
        )

        # Send request for operation
        server.send_request_for_operation(operation.token, request)

        # Verify operation status changed
        updated_op = manager.get_operation(operation.token)
        assert updated_op is not None
        assert updated_op.status == "input_required"

    @pytest.mark.anyio
    async def test_server_complete_request_for_operation(self):
        """Test server method for completing requests."""
        manager = ServerAsyncOperationManager()
        server = Server("Test", async_operations=manager)

        # Create operation and mark as input required
        operation = manager.create_operation("test_tool", {"arg": "value"}, session_id="session1")
        manager.mark_input_required(operation.token)

        # Complete request for operation
        server.complete_request_for_operation(operation.token)

        # Verify operation status changed back to working
        updated_op = manager.get_operation(operation.token)
        assert updated_op is not None
        assert updated_op.status == "working"

    @pytest.mark.anyio
    async def test_input_required_is_terminal_check(self):
        """Test that input_required is not considered a terminal state."""
        manager = ServerAsyncOperationManager()

        # Create operation and mark as input required
        operation = manager.create_operation("test_tool", {"arg": "value"}, session_id="session1")
        manager.mark_input_required(operation.token)

        # Verify it's not terminal
        assert not operation.is_terminal

        # Verify it doesn't expire while in input_required state
        assert not operation.is_expired
