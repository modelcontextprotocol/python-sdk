"""Async operations management for FastMCP servers."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import mcp.types as types
from mcp.types import AsyncOperationStatus


@dataclass
class ClientAsyncOperation:
    """Minimal operation tracking for client-side use."""

    token: str
    tool_name: str
    created_at: float
    keep_alive: int

    @property
    def is_expired(self) -> bool:
        """Check if operation has expired based on keepAlive."""
        return time.time() > (self.created_at + self.keep_alive)


@dataclass
class ServerAsyncOperation:
    """Represents an async tool operation."""

    token: str
    tool_name: str
    arguments: dict[str, Any]
    status: AsyncOperationStatus
    created_at: float
    keep_alive: int
    session_id: str | None = None
    result: types.CallToolResult | None = None
    error: str | None = None

    @property
    def is_expired(self) -> bool:
        """Check if operation has expired based on keepAlive."""
        if self.status in ("completed", "failed", "canceled"):
            return time.time() > (self.created_at + self.keep_alive)
        return False

    @property
    def is_terminal(self) -> bool:
        """Check if operation is in a terminal state."""
        return self.status in ("completed", "failed", "canceled", "unknown")


OperationT = TypeVar("OperationT", ClientAsyncOperation, ServerAsyncOperation)


class BaseOperationManager(Generic[OperationT]):
    """Base class for operation management."""

    def __init__(self, *, token_generator: Callable[[str | None], str] | None = None):
        self._operations: dict[str, OperationT] = {}
        self._cleanup_task: asyncio.Task[None] | None = None
        self._cleanup_interval = 60  # Cleanup every 60 seconds
        self._token_generator = token_generator or self._default_token_generator

    def _default_token_generator(self, session_id: str | None = None) -> str:
        """Default token generation using random tokens."""
        return secrets.token_urlsafe(32)

    def generate_token(self, session_id: str | None = None) -> str:
        """Generate a token."""
        return self._token_generator(session_id)

    def _get_operation(self, token: str) -> OperationT | None:
        """Internal method to get operation by token."""
        return self._operations.get(token)

    def _set_operation(self, token: str, operation: OperationT) -> None:
        """Internal method to store an operation."""
        self._operations[token] = operation

    def _remove_operation(self, token: str) -> OperationT | None:
        """Internal method to remove and return an operation."""
        return self._operations.pop(token, None)

    def get_operation(self, token: str) -> OperationT | None:
        """Get operation by token."""
        return self._get_operation(token)

    def remove_operation(self, token: str) -> bool:
        """Remove an operation by token."""
        return self._remove_operation(token) is not None

    def cleanup_expired(self) -> int:
        """Remove expired operations and return count of removed operations."""
        expired_tokens = [token for token, operation in self._operations.items() if operation.is_expired]
        for token in expired_tokens:
            self._remove_operation(token)
        return len(expired_tokens)

    async def start_cleanup_task(self) -> None:
        """Start the background cleanup task."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop_cleanup_task(self) -> None:
        """Stop the background cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    async def _cleanup_loop(self) -> None:
        """Background task to clean up expired operations."""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                count = self.cleanup_expired()
                if count > 0:
                    print(f"Cleaned up {count} expired operations")
            except asyncio.CancelledError:
                break


class ClientAsyncOperationManager(BaseOperationManager[ClientAsyncOperation]):
    """Manages client-side operation tracking."""

    def track_operation(self, token: str, tool_name: str, keep_alive: int = 3600) -> None:
        """Track a client operation."""
        operation = ClientAsyncOperation(
            token=token,
            tool_name=tool_name,
            created_at=time.time(),
            keep_alive=keep_alive,
        )
        self._set_operation(token, operation)

    def get_tool_name(self, token: str) -> str | None:
        """Get tool name for a tracked operation."""
        operation = self._get_operation(token)
        return operation.tool_name if operation else None


class ServerAsyncOperationManager(BaseOperationManager[ServerAsyncOperation]):
    """Manages async tool operations with token-based tracking."""

    def create_operation(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        keep_alive: int = 3600,
        session_id: str | None = None,
    ) -> ServerAsyncOperation:
        """Create a new async operation."""
        token = self.generate_token(session_id)
        operation = ServerAsyncOperation(
            token=token,
            tool_name=tool_name,
            arguments=arguments,
            status="submitted",
            created_at=time.time(),
            keep_alive=keep_alive,
            session_id=session_id,
        )
        self._set_operation(token, operation)
        return operation

    def mark_working(self, token: str) -> bool:
        """Mark operation as working."""
        operation = self._get_operation(token)
        if not operation:
            return False

        # Can only transition to working from submitted
        if operation.status != "submitted":
            return False

        operation.status = "working"
        return True

    def complete_operation(self, token: str, result: types.CallToolResult) -> bool:
        """Complete operation with result."""
        operation = self._get_operation(token)
        if not operation:
            return False

        # Can only complete from submitted or working states
        if operation.status not in ("submitted", "working"):
            return False

        operation.status = "completed"
        operation.result = result
        return True

    def fail_operation(self, token: str, error: str) -> bool:
        """Fail operation with error."""
        operation = self._get_operation(token)
        if not operation:
            return False

        # Can only fail from submitted or working states
        if operation.status not in ("submitted", "working"):
            return False

        operation.status = "failed"
        operation.error = error
        return True

    def get_operation_result(self, token: str) -> types.CallToolResult | None:
        """Get result for completed operation."""
        operation = self._get_operation(token)
        if not operation or operation.status != "completed":
            return None
        return operation.result

    def cancel_operation(self, token: str) -> bool:
        """Cancel operation."""
        operation = self._get_operation(token)
        if not operation:
            return False

        # Can only cancel from submitted or working states
        if operation.status not in ("submitted", "working"):
            return False

        operation.status = "canceled"
        return True

    def remove_operation(self, token: str) -> bool:
        """Remove operation by token."""
        return self._operations.pop(token, None) is not None

    def cleanup_expired_operations(self) -> int:
        """Remove expired operations and return count removed."""
        expired_tokens = [token for token, op in self._operations.items() if op.is_expired]

        for token in expired_tokens:
            del self._operations[token]

        return len(expired_tokens)

    def get_session_operations(self, session_id: str) -> list[ServerAsyncOperation]:
        """Get all operations for a session."""
        return [op for op in self._operations.values() if op.session_id == session_id]

    def cancel_session_operations(self, session_id: str) -> int:
        """Cancel all operations for a session."""
        session_ops = self.get_session_operations(session_id)
        canceled_count = 0

        for op in session_ops:
            if not op.is_terminal:
                op.status = "canceled"
                canceled_count += 1

        return canceled_count

    def mark_input_required(self, token: str) -> bool:
        """Mark operation as requiring input from client."""
        operation = self._get_operation(token)
        if not operation:
            return False

        # Can only move to input_required from submitted or working states
        if operation.status not in ("submitted", "working"):
            return False

        operation.status = "input_required"
        return True

    def mark_input_completed(self, token: str) -> bool:
        """Mark operation as no longer requiring input, return to working state."""
        operation = self._get_operation(token)
        if not operation:
            return False

        # Can only move from input_required back to working
        if operation.status != "input_required":
            return False

        operation.status = "working"
        return True

    async def start_cleanup_task(self) -> None:
        """Start the background cleanup task."""
        if self._cleanup_task is not None:
            return

        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop_cleanup_task(self) -> None:
        """Stop the background cleanup task."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    async def _cleanup_loop(self) -> None:
        """Background cleanup loop."""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                self.cleanup_expired_operations()
            except asyncio.CancelledError:
                break
            except Exception:
                # Log error but continue cleanup loop
                pass
