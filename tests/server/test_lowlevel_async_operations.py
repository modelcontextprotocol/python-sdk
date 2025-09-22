"""Test async operations integration in lowlevel Server."""

import asyncio
import time
from typing import cast

import pytest

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.async_operations import AsyncOperationManager
from mcp.shared.exceptions import McpError


class TestLowlevelServerAsyncOperations:
    """Test lowlevel Server async operations integration."""

    def test_check_async_status_invalid_token(self):
        """Test check_tool_async_status handler with invalid token."""
        manager = AsyncOperationManager()
        server = Server("Test", async_operations=manager)

        # Register the handler
        @server.check_tool_async_status()
        async def check_status_handler(token: str) -> types.CheckToolAsyncStatusResult:
            # This function is not actually called due to built-in logic
            return types.CheckToolAsyncStatusResult(status="unknown")

        # Test invalid token
        invalid_request = types.CheckToolAsyncStatusRequest(
            params=types.CheckToolAsyncStatusParams(token="invalid_token")
        )

        handler = server.request_handlers[types.CheckToolAsyncStatusRequest]

        with pytest.raises(McpError) as exc_info:

            async def run_handler():
                return await handler(invalid_request)

            asyncio.run(run_handler())

        assert exc_info.value.error.code == -32602
        assert exc_info.value.error.message == "Invalid token"

    def test_check_async_status_expired_token(self):
        """Test check_tool_async_status handler with expired token."""
        manager = AsyncOperationManager()
        server = Server("Test", async_operations=manager)

        @server.check_tool_async_status()
        async def check_status_handler(token: str) -> types.CheckToolAsyncStatusResult:
            return types.CheckToolAsyncStatusResult(status="unknown")

        # Create and complete operation with short keepAlive
        operation = manager.create_operation("test_tool", {}, "session1", keep_alive=1)
        manager.complete_operation(operation.token, types.CallToolResult(content=[]))

        # Make it expired
        operation.created_at = time.time() - 2

        expired_request = types.CheckToolAsyncStatusRequest(
            params=types.CheckToolAsyncStatusParams(token=operation.token)
        )

        handler = server.request_handlers[types.CheckToolAsyncStatusRequest]

        with pytest.raises(McpError) as exc_info:

            async def run_handler():
                return await handler(expired_request)

            asyncio.run(run_handler())

        assert exc_info.value.error.code == -32602
        assert exc_info.value.error.message == "Token expired"

    def test_check_async_status_valid_operation(self):
        """Test check_tool_async_status handler with valid operation."""
        manager = AsyncOperationManager()
        server = Server("Test", async_operations=manager)

        @server.check_tool_async_status()
        async def check_status_handler(token: str) -> types.CheckToolAsyncStatusResult:
            return types.CheckToolAsyncStatusResult(status="unknown")

        # Create valid operation
        operation = manager.create_operation("test_tool", {}, "session1")
        manager.mark_working(operation.token)

        valid_request = types.CheckToolAsyncStatusRequest(
            params=types.CheckToolAsyncStatusParams(token=operation.token)
        )

        handler = server.request_handlers[types.CheckToolAsyncStatusRequest]

        async def run_handler():
            return await handler(valid_request)

        result = asyncio.run(run_handler())

        assert isinstance(result, types.ServerResult)
        status_result = cast(types.CheckToolAsyncStatusResult, result.root)
        assert status_result.status == "working"
        assert status_result.error is None

    def test_check_async_status_failed_operation(self):
        """Test check_tool_async_status handler with failed operation."""
        manager = AsyncOperationManager()
        server = Server("Test", async_operations=manager)

        @server.check_tool_async_status()
        async def check_status_handler(token: str) -> types.CheckToolAsyncStatusResult:
            return types.CheckToolAsyncStatusResult(status="unknown")

        # Create and fail operation
        operation = manager.create_operation("test_tool", {}, "session1")
        manager.fail_operation(operation.token, "Something went wrong")

        failed_request = types.CheckToolAsyncStatusRequest(
            params=types.CheckToolAsyncStatusParams(token=operation.token)
        )

        handler = server.request_handlers[types.CheckToolAsyncStatusRequest]

        async def run_handler():
            return await handler(failed_request)

        result = asyncio.run(run_handler())

        assert isinstance(result, types.ServerResult)
        status_result = cast(types.CheckToolAsyncStatusResult, result.root)
        assert status_result.status == "failed"
        assert status_result.error == "Something went wrong"

    def test_get_async_result_invalid_token(self):
        """Test get_tool_async_result handler with invalid token."""
        manager = AsyncOperationManager()
        server = Server("Test", async_operations=manager)

        @server.get_tool_async_result()
        async def get_result_handler(token: str) -> types.GetToolAsyncPayloadResult:
            return types.GetToolAsyncPayloadResult(result=types.CallToolResult(content=[]))

        invalid_request = types.GetToolAsyncPayloadRequest(
            params=types.GetToolAsyncPayloadParams(token="invalid_token")
        )

        handler = server.request_handlers[types.GetToolAsyncPayloadRequest]

        with pytest.raises(McpError) as exc_info:

            async def run_handler():
                return await handler(invalid_request)

            asyncio.run(run_handler())

        assert exc_info.value.error.code == -32602
        assert exc_info.value.error.message == "Invalid token"

    def test_get_async_result_expired_token(self):
        """Test get_tool_async_result handler with expired token."""
        manager = AsyncOperationManager()
        server = Server("Test", async_operations=manager)

        @server.get_tool_async_result()
        async def get_result_handler(token: str) -> types.GetToolAsyncPayloadResult:
            return types.GetToolAsyncPayloadResult(result=types.CallToolResult(content=[]))

        # Create and complete operation with short keepAlive
        operation = manager.create_operation("test_tool", {}, "session1", keep_alive=1)
        manager.complete_operation(operation.token, types.CallToolResult(content=[]))

        # Make it expired
        operation.created_at = time.time() - 2

        expired_request = types.GetToolAsyncPayloadRequest(
            params=types.GetToolAsyncPayloadParams(token=operation.token)
        )

        handler = server.request_handlers[types.GetToolAsyncPayloadRequest]

        with pytest.raises(McpError) as exc_info:

            async def run_handler():
                return await handler(expired_request)

            asyncio.run(run_handler())

        assert exc_info.value.error.code == -32602
        assert exc_info.value.error.message == "Token expired"

    def test_get_async_result_not_completed(self):
        """Test get_tool_async_result handler with non-completed operation."""
        manager = AsyncOperationManager()
        server = Server("Test", async_operations=manager)

        @server.get_tool_async_result()
        async def get_result_handler(token: str) -> types.GetToolAsyncPayloadResult:
            return types.GetToolAsyncPayloadResult(result=types.CallToolResult(content=[]))

        # Create operation that's still working
        operation = manager.create_operation("test_tool", {}, "session1")
        manager.mark_working(operation.token)

        working_request = types.GetToolAsyncPayloadRequest(
            params=types.GetToolAsyncPayloadParams(token=operation.token)
        )

        handler = server.request_handlers[types.GetToolAsyncPayloadRequest]

        with pytest.raises(McpError) as exc_info:

            async def run_handler():
                return await handler(working_request)

            asyncio.run(run_handler())

        assert exc_info.value.error.code == -32600
        assert exc_info.value.error.message == "Operation not completed (status: working)"

    def test_get_async_result_completed_with_result(self):
        """Test get_tool_async_result handler with completed operation."""
        manager = AsyncOperationManager()
        server = Server("Test", async_operations=manager)

        @server.get_tool_async_result()
        async def get_result_handler(token: str) -> types.GetToolAsyncPayloadResult:
            return types.GetToolAsyncPayloadResult(result=types.CallToolResult(content=[]))

        # Create and complete operation with result
        operation = manager.create_operation("test_tool", {}, "session1")
        result = types.CallToolResult(content=[types.TextContent(type="text", text="success")])
        manager.complete_operation(operation.token, result)

        completed_request = types.GetToolAsyncPayloadRequest(
            params=types.GetToolAsyncPayloadParams(token=operation.token)
        )

        handler = server.request_handlers[types.GetToolAsyncPayloadRequest]

        async def run_handler():
            return await handler(completed_request)

        response = asyncio.run(run_handler())

        assert isinstance(response, types.ServerResult)
        payload_result = cast(types.GetToolAsyncPayloadResult, response.root)
        assert payload_result.result == result
