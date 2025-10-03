"""Tests for AsyncOperationManager."""

import secrets
import time
from typing import Any, cast
from unittest.mock import Mock

import pytest

import mcp.types as types
from mcp.shared.async_operations import ServerAsyncOperation, ServerAsyncOperationManager
from mcp.types import AsyncOperationStatus


class TestAsyncOperationManager:
    """Test AsyncOperationManager functionality."""

    def _create_manager_with_operation(
        self, session_id: str = "session1", **kwargs: Any
    ) -> tuple[ServerAsyncOperationManager, ServerAsyncOperation]:
        """Helper to create manager with a test operation."""
        manager = ServerAsyncOperationManager()
        operation = manager.create_operation("test_tool", {"arg": "value"}, session_id=session_id, **kwargs)
        return manager, operation

    def test_token_generation(self):
        """Test token generation with default and custom generators."""
        # Default token generation
        manager = ServerAsyncOperationManager()
        token1 = manager.generate_token("test_session")
        token2 = manager.generate_token("test_session")
        assert token1 != token2 and len(token1) > 20 and not token1.startswith("test_session_")

        # Custom token generator
        custom_manager = ServerAsyncOperationManager(token_generator=lambda sid: f"custom_{sid}_token")
        assert custom_manager.generate_token("test") == "custom_test_token"

        # Session-scoped token generator
        scoped_manager = ServerAsyncOperationManager(token_generator=lambda sid: f"{sid}_{secrets.token_urlsafe(16)}")
        token1, token2 = scoped_manager.generate_token("s1"), scoped_manager.generate_token("s2")
        assert token1.startswith("s1_") and token2.startswith("s2_") and token1 != token2

    def test_operation_lifecycle(self):
        """Test complete operation lifecycle including direct transitions."""
        manager, operation = self._create_manager_with_operation()
        token = operation.token

        # Test creation
        assert operation.status == "submitted" and operation.result is None

        # Test working transition
        assert manager.mark_working(token)
        working_op = manager.get_operation(token)
        assert working_op is not None and working_op.status == "working"

        # Test completion
        result = types.CallToolResult(content=[types.TextContent(type="text", text="success")])
        assert manager.complete_operation(token, result)
        completed_op = manager.get_operation(token)
        assert completed_op is not None
        assert completed_op.status == "completed" and completed_op.result == result
        assert manager.get_operation_result(token) == result

        # Test direct completion from submitted (new manager to avoid interference)
        direct_manager, direct_op = self._create_manager_with_operation()
        assert direct_manager.complete_operation(direct_op.token, result)
        direct_completed = direct_manager.get_operation(direct_op.token)
        assert direct_completed is not None and direct_completed.status == "completed"

        # Test direct failure from submitted (new manager to avoid interference)
        fail_manager, fail_op = self._create_manager_with_operation()
        assert fail_manager.fail_operation(fail_op.token, "immediate error")
        failed = fail_manager.get_operation(fail_op.token)
        assert failed is not None
        assert failed.status == "failed" and failed.error == "immediate error"

    def test_operation_failure_and_cancellation(self):
        """Test operation failure and cancellation."""
        manager, operation = self._create_manager_with_operation()

        # Test failure
        manager.mark_working(operation.token)
        assert manager.fail_operation(operation.token, "Something went wrong")
        failed_op = manager.get_operation(operation.token)
        assert failed_op is not None
        assert failed_op.status == "failed" and failed_op.error == "Something went wrong"
        assert manager.get_operation_result(operation.token) is None

        # Test cancellation (new manager to avoid interference)
        cancel_manager, cancel_op = self._create_manager_with_operation()
        assert cancel_manager.cancel_operation(cancel_op.token)
        canceled_op = cancel_manager.get_operation(cancel_op.token)
        assert canceled_op is not None and canceled_op.status == "canceled"

    def test_state_transitions_and_terminal_states(self):
        """Test state transition validation and terminal state immutability."""
        manager, operation = self._create_manager_with_operation()
        token = operation.token
        result = Mock()

        # Valid transitions
        assert manager.mark_working(token)
        assert manager.complete_operation(token, result)

        # Invalid transitions from terminal state
        assert not manager.mark_working(token)
        assert not manager.fail_operation(token, "error")
        assert not manager.cancel_operation(token)
        completed_check = manager.get_operation(token)
        assert completed_check is not None and completed_check.status == "completed"

        # Test other terminal states (use separate managers since previous operation is already completed)
        def fail_action(m: ServerAsyncOperationManager, t: str) -> bool:
            return m.fail_operation(t, "err")

        def cancel_action(m: ServerAsyncOperationManager, t: str) -> bool:
            return m.cancel_operation(t)

        for status, action in [
            ("failed", fail_action),
            ("canceled", cancel_action),
        ]:
            test_manager, test_op = self._create_manager_with_operation()
            action(test_manager, test_op.token)
            terminal_op = test_manager.get_operation(test_op.token)
            assert terminal_op is not None
            assert terminal_op.status == status and terminal_op.is_terminal

    def test_nonexistent_token_operations(self):
        """Test operations on nonexistent tokens."""
        manager = ServerAsyncOperationManager()
        fake_token = "fake_token"

        for method, args in [
            ("get_operation", ()),
            ("mark_working", ()),
            ("complete_operation", (Mock(),)),
            ("fail_operation", ("error",)),
            ("cancel_operation", ()),
            ("get_operation_result", ()),
            ("remove_operation", ()),
        ]:
            assert getattr(manager, method)(fake_token, *args) in (None, False)

    def test_session_management(self):
        """Test session-based operation management and termination."""
        manager = ServerAsyncOperationManager()

        # Create operations for different sessions
        ops = [manager.create_operation(f"tool{i}", {}, session_id=f"session{i % 2}") for i in range(4)]

        # Test session filtering
        s0_ops = manager.get_session_operations("session0")
        s1_ops = manager.get_session_operations("session1")
        assert len(s0_ops) == 2 and len(s1_ops) == 2

        # Test session termination - ops[0] and ops[2] are in session0
        manager.mark_working(ops[0].token)  # session0 - should be canceled
        manager.complete_operation(ops[2].token, Mock())  # session0 - should NOT be canceled (completed)

        canceled_count = manager.cancel_session_operations("session0")
        assert canceled_count == 1  # Only working operation canceled, not completed

        s0_after = manager.get_session_operations("session0")
        # Find the operations by status since order might vary
        working_op = next(op for op in s0_after if op.token == ops[0].token)
        completed_op = next(op for op in s0_after if op.token == ops[2].token)
        assert working_op.status == "canceled" and completed_op.status == "completed"

    def test_expiration_and_cleanup(self):
        """Test operation expiration and cleanup."""
        manager = ServerAsyncOperationManager()

        # Create operations with different expiration times
        short_op = manager.create_operation("tool1", {}, keep_alive=1, session_id="session1")
        long_op = manager.create_operation("tool2", {}, keep_alive=10, session_id="session1")

        # Complete both and make first expired
        for op in [short_op, long_op]:
            manager.complete_operation(op.token, Mock())
        short_op.resolved_at = time.time() - 2

        # Test expiration detection
        assert short_op.is_expired and not long_op.is_expired

        # Test cleanup
        removed_count = manager.cleanup_expired_operations()
        assert removed_count == 1
        assert manager.get_operation(short_op.token) is None
        assert manager.get_operation(long_op.token) is not None

    def test_concurrent_operations(self):
        """Test concurrent operation handling and memory management."""
        manager = ServerAsyncOperationManager()

        # Create many operations
        operations = [
            manager.create_operation(f"tool_{i}", {"data": "x" * 100}, session_id=f"session_{i % 3}") for i in range(50)
        ]

        # All should be created successfully with unique tokens
        assert len(operations) == 50
        tokens = [op.token for op in operations]
        assert len(set(tokens)) == 50

        # Complete half with short keepAlive and make them expired
        for i in range(25):
            manager.complete_operation(operations[i].token, Mock())
            operations[i].keep_alive = 1
            operations[i].resolved_at = time.time() - 2

        # Cleanup should remove expired operations
        removed_count = manager.cleanup_expired_operations()
        assert removed_count == 25 and len(manager._operations) == 25

    @pytest.mark.anyio
    async def test_cleanup_task_lifecycle(self):
        """Test background cleanup task management."""
        manager = ServerAsyncOperationManager()

        await manager.start_cleanup_task()
        assert manager._cleanup_task is not None and not manager._cleanup_task.done()

        # Starting again should be no-op
        await manager.start_cleanup_task()

        await manager.stop_cleanup_task()
        assert manager._cleanup_task is None

    def test_dependency_injection_and_integration(self):
        """Test AsyncOperationManager dependency injection and server integration."""
        from mcp.server.fastmcp import FastMCP
        from mcp.server.lowlevel import Server

        # Test custom manager injection
        custom_manager = ServerAsyncOperationManager()
        operation = custom_manager.create_operation("shared_tool", {"data": "shared"}, session_id="session1")

        # Test FastMCP integration
        fastmcp = FastMCP("FastMCP", async_operations=custom_manager)
        assert fastmcp._async_operations is custom_manager
        assert fastmcp._async_operations.get_operation(operation.token) is operation

        # Test lowlevel Server integration
        lowlevel = Server("LowLevel", async_operations=custom_manager)
        assert lowlevel.async_operations is custom_manager
        assert lowlevel.async_operations.get_operation(operation.token) is operation

        # Test default creation
        default_fastmcp = FastMCP("Default")
        default_server = Server("Default")
        assert isinstance(default_fastmcp._async_operations, ServerAsyncOperationManager)
        assert isinstance(default_server.async_operations, ServerAsyncOperationManager)
        assert default_fastmcp._async_operations is not custom_manager

        # Test shared manager between servers
        new_op = fastmcp._async_operations.create_operation("new_tool", {}, session_id="session2")
        assert lowlevel.async_operations.get_operation(new_op.token) is new_op


class TestAsyncOperation:
    """Test AsyncOperation dataclass."""

    def test_terminal_and_expiration_logic(self):
        """Test terminal state detection and expiration logic."""
        now = time.time()
        operation = ServerAsyncOperation("test", "test", {}, "submitted", now, 3600)

        # Test terminal state detection
        for status_str, is_terminal in [
            ("submitted", False),
            ("working", False),
            ("completed", True),
            ("failed", True),
            ("canceled", True),
            ("unknown", True),
        ]:
            status: AsyncOperationStatus = cast(AsyncOperationStatus, status_str)
            operation.status = status
            assert operation.is_terminal == is_terminal

        # Test expiration logic
        working_status: AsyncOperationStatus = "working"
        operation.status = working_status
        assert not operation.is_expired  # Non-terminal never expires

        completed_status: AsyncOperationStatus = "completed"
        operation.status = completed_status
        operation.resolved_at = now - 1800  # 30 minutes ago
        assert not operation.is_expired  # Within keepAlive

        operation.resolved_at = now - 7200  # 2 hours ago
        assert operation.is_expired  # Past keepAlive
