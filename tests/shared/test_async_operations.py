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

    async def _create_manager_with_operation(
        self, session_id: str = "session1", **kwargs: Any
    ) -> tuple[ServerAsyncOperationManager, ServerAsyncOperation]:
        """Helper to create manager with a test operation."""
        manager = ServerAsyncOperationManager()
        operation = await manager.create_operation("test_tool", {"arg": "value"}, session_id=session_id, **kwargs)
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

    @pytest.mark.anyio
    async def test_operation_lifecycle(self):
        """Test complete operation lifecycle including direct transitions."""
        manager, operation = await self._create_manager_with_operation()
        token = operation.token

        # Test creation
        assert operation.status == "submitted" and operation.result is None

        # Test working transition
        assert await manager.mark_working(token)
        working_op = await manager.get_operation(token)
        assert working_op is not None and working_op.status == "working"

        # Test completion
        result = types.CallToolResult(content=[types.TextContent(type="text", text="success")])
        assert await manager.complete_operation(token, result)
        completed_op = await manager.get_operation(token)
        assert completed_op is not None
        assert completed_op.status == "completed" and completed_op.result == result
        assert await manager.get_operation_result(token) == result

        # Test direct completion from submitted (new manager to avoid interference)
        direct_manager, direct_op = await self._create_manager_with_operation()
        assert await direct_manager.complete_operation(direct_op.token, result)
        direct_completed = await direct_manager.get_operation(direct_op.token)
        assert direct_completed is not None and direct_completed.status == "completed"

        # Test direct failure from submitted (new manager to avoid interference)
        fail_manager, fail_op = await self._create_manager_with_operation()
        assert await fail_manager.fail_operation(fail_op.token, "immediate error")
        failed = await fail_manager.get_operation(fail_op.token)
        assert failed is not None
        assert failed.status == "failed" and failed.error == "immediate error"

    @pytest.mark.anyio
    async def test_operation_failure_and_cancellation(self):
        """Test operation failure and cancellation."""
        manager, operation = await self._create_manager_with_operation()

        # Test failure
        await manager.mark_working(operation.token)
        assert await manager.fail_operation(operation.token, "Something went wrong")
        failed_op = await manager.get_operation(operation.token)
        assert failed_op is not None
        assert failed_op.status == "failed" and failed_op.error == "Something went wrong"
        assert await manager.get_operation_result(operation.token) is None

        # Test cancellation (new manager to avoid interference)
        cancel_manager, cancel_op = await self._create_manager_with_operation()
        assert await cancel_manager.cancel_operation(cancel_op.token)
        canceled_op = await cancel_manager.get_operation(cancel_op.token)
        assert canceled_op is not None and canceled_op.status == "canceled"

    @pytest.mark.anyio
    async def test_state_transitions_and_terminal_states(self):
        """Test state transition validation and terminal state immutability."""
        manager, operation = await self._create_manager_with_operation()
        token = operation.token
        result = Mock()

        # Valid transitions
        assert await manager.mark_working(token)
        assert await manager.complete_operation(token, result)

        # Invalid transitions from terminal state
        assert not await manager.mark_working(token)
        assert not await manager.fail_operation(token, "error")
        assert not await manager.cancel_operation(token)
        completed_check = await manager.get_operation(token)
        assert completed_check is not None and completed_check.status == "completed"

        # Test other terminal states (use separate managers since previous operation is already completed)
        async def fail_action(m: ServerAsyncOperationManager, t: str) -> bool:
            return await m.fail_operation(t, "err")

        async def cancel_action(m: ServerAsyncOperationManager, t: str) -> bool:
            return await m.cancel_operation(t)

        for status, action in [
            ("failed", fail_action),
            ("canceled", cancel_action),
        ]:
            test_manager, test_op = await self._create_manager_with_operation()
            await action(test_manager, test_op.token)
            terminal_op = await test_manager.get_operation(test_op.token)
            assert terminal_op is not None
            assert terminal_op.status == status and terminal_op.is_terminal

    @pytest.mark.anyio
    async def test_nonexistent_token_operations(self):
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
        ]:
            result = await getattr(manager, method)(fake_token, *args)
            assert result in (None, False)

    @pytest.mark.anyio
    async def test_expiration_and_cleanup(self):
        """Test operation expiration and cleanup."""
        manager = ServerAsyncOperationManager()

        # Create operations with different expiration times
        short_op = await manager.create_operation("tool1", {}, keep_alive=1, session_id="session1")
        long_op = await manager.create_operation("tool2", {}, keep_alive=10, session_id="session1")

        # Complete both and make first expired
        for op in [short_op, long_op]:
            await manager.complete_operation(op.token, Mock())
        short_op.resolved_at = time.time() - 2

        # Test expiration detection
        assert short_op.is_expired and not long_op.is_expired

        # Test cleanup
        removed_count = await manager.cleanup_expired()
        assert removed_count == 1
        assert await manager.get_operation(short_op.token) is None
        assert await manager.get_operation(long_op.token) is not None

    @pytest.mark.anyio
    async def test_concurrent_operations(self):
        """Test concurrent operation handling and memory management."""
        manager = ServerAsyncOperationManager()

        # Create many operations
        operations = [
            await manager.create_operation(f"tool_{i}", {"data": "x" * 100}, session_id=f"session_{i % 3}")
            for i in range(50)
        ]

        # All should be created successfully with unique tokens
        assert len(operations) == 50
        tokens = [op.token for op in operations]
        assert len(set(tokens)) == 50

        # Complete half with short keepAlive and make them expired
        for i in range(25):
            await manager.complete_operation(operations[i].token, Mock())
            operations[i].keep_alive = 1
            operations[i].resolved_at = time.time() - 2

        # Cleanup should remove expired operations
        removed_count = await manager.cleanup_expired()
        assert removed_count == 25


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
