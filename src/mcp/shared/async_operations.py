"""Async operations management for FastMCP servers."""

from __future__ import annotations

import contextlib
import logging
import secrets
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar

import anyio
from anyio.abc import TaskGroup

import mcp.types as types
from mcp.types import AsyncOperationStatus

if TYPE_CHECKING:
    # Avoid circular import with mcp.server.lowlevel.Server
    from mcp.server.session import ServerSession
    from mcp.shared.context import RequestContext

logger = logging.getLogger(__name__)


@dataclass
class PendingAsyncTask:
    """Represents a task waiting to be dispatched."""

    token: str
    tool_name: str
    arguments: dict[str, Any]
    request_context: Any  # The RequestContext object to restore


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
        return time.time() > (self.created_at + self.keep_alive * 2)  # Give some buffer before expiration


@dataclass
class ServerAsyncOperation:
    """Represents an async tool operation."""

    token: str
    tool_name: str
    arguments: dict[str, Any]
    status: AsyncOperationStatus
    created_at: float
    keep_alive: int
    resolved_at: float | None = None
    session_id: str | None = None
    result: types.CallToolResult | None = None
    error: str | None = None

    @property
    def is_expired(self) -> bool:
        """Check if operation has expired based on keepAlive."""
        if not self.resolved_at:
            return False
        if self.status in ("completed", "failed", "canceled"):
            return time.time() > (self.resolved_at + self.keep_alive)
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
        self._cleanup_interval = 60  # Cleanup every 60 seconds
        self._token_generator = token_generator or self._default_token_generator
        self._running = False

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

    async def stop_cleanup_loop(self) -> None:
        self._running = False

    async def cleanup_loop(self) -> None:
        """Background task to clean up expired operations."""
        if self._running:
            return
        self._running = True

        while self._running:
            await anyio.sleep(self._cleanup_interval)
            count = self.cleanup_expired()
            if count > 0:
                logger.debug(f"Cleaned up {count} expired operations")


class AsyncOperationStore(Protocol):
    """Protocol for async operation storage implementations."""

    async def get_operation(self, token: str) -> ServerAsyncOperation | None:
        """Get operation by token."""
        ...

    async def store_operation(self, operation: ServerAsyncOperation) -> None:
        """Store an operation."""
        ...

    async def update_status(self, token: str, status: AsyncOperationStatus) -> bool:
        """Update operation status."""
        ...

    async def complete_operation_with_result(self, token: str, result: types.CallToolResult) -> bool:
        """Complete operation with result."""
        ...

    async def fail_operation_with_error(self, token: str, error: str) -> bool:
        """Fail operation with error."""
        ...

    async def cleanup_expired(self) -> int:
        """Remove expired operations and return count."""
        ...


class AsyncOperationBroker(Protocol):
    """Protocol for async operation queueing and scheduling."""

    async def enqueue_task(
        self,
        token: str,
        tool_name: str,
        arguments: dict[str, Any],
        request_context: RequestContext[ServerSession, Any, Any],
    ) -> None:
        """Enqueue a task for execution."""
        ...

    async def get_pending_tasks(self) -> list[PendingAsyncTask]:
        """Get all pending tasks."""
        ...

    async def acknowledge_task(self, token: str) -> None:
        """Acknowledge that a task has been dispatched."""
        ...

    async def complete_task(self, token: str) -> None:
        """Remove a completed task from persistent storage."""
        ...


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


class ServerAsyncOperationManager:
    """Manages async tool operations using Store and Broker components."""

    def __init__(
        self,
        store: AsyncOperationStore | None = None,
        broker: AsyncOperationBroker | None = None,
        *,
        token_generator: Callable[[str | None], str] | None = None,
    ):
        # Use provided implementations or default to InMemory
        self.store = store or InMemoryAsyncOperationStore()
        self.broker = broker or InMemoryAsyncOperationBroker()
        self._token_generator = token_generator or self._default_token_generator
        self._tool_executor: Callable[[str, dict[str, Any], Any], Awaitable[types.CallToolResult]] | None = None
        self._task_group: TaskGroup | None = None
        self._run_lock = anyio.Lock()
        self._running = False

    def set_handler(self, tool_executor: Callable[[str, dict[str, Any], Any], Awaitable[types.CallToolResult]]) -> None:
        """Set the tool executor handler for late binding."""
        self._tool_executor = tool_executor

    def _default_token_generator(self, session_id: str | None = None) -> str:
        """Default token generation using random tokens."""
        return secrets.token_urlsafe(32)

    def generate_token(self, session_id: str | None = None) -> str:
        """Generate a token."""
        return self._token_generator(session_id)

    @contextlib.asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        """Run the async operations manager with its own task group."""
        # Thread-safe check to ensure run() is only called once
        async with self._run_lock:
            if self._running:
                raise RuntimeError("ServerAsyncOperationManager.run() is already running.")
            self._running = True

        async with anyio.create_task_group() as tg:
            self._task_group = tg
            logger.info("ServerAsyncOperationManager started")
            # Start cleanup loop and task dispatcher
            tg.start_soon(self._cleanup_loop)
            tg.start_soon(self._task_dispatcher)
            try:
                yield
            finally:
                logger.info("ServerAsyncOperationManager shutting down")
                # Stop cleanup loop gracefully
                await self._stop_cleanup_loop()
                # Cancel task group to stop all spawned tasks
                tg.cancel_scope.cancel()
                self._task_group = None
                self._running = False

    async def _cleanup_loop(self) -> None:
        """Background cleanup loop for expired operations."""
        while self._running:
            await anyio.sleep(60)  # Cleanup every 60 seconds
            count = await self.store.cleanup_expired()
            if count > 0:
                logger.debug(f"Cleaned up {count} expired operations")

    async def _stop_cleanup_loop(self) -> None:
        """Stop the cleanup loop."""
        self._running = False

    async def _task_dispatcher(self) -> None:
        """Background task dispatcher that processes queued tasks."""
        while self._running:
            await anyio.sleep(0.1)  # Check for tasks frequently
            pending_tasks = await self.broker.get_pending_tasks()
            for task in pending_tasks:
                if self._task_group and self._tool_executor:
                    logger.debug(f"Dispatching queued async task {task.token}")
                    self._task_group.start_soon(self._execute_tool_task, task, name=f"lro_{task.token}")
                    # Acknowledge that we've dispatched this task
                    await self.broker.acknowledge_task(task.token)

    async def _execute_tool_task(self, task: PendingAsyncTask) -> None:
        """Execute a tool task."""
        try:
            if not self._tool_executor:
                raise ValueError("No tool executor configured")

            await self.mark_working(task.token)
            result = await self._tool_executor(task.tool_name, task.arguments, task.request_context)
            await self.complete_operation(task.token, result)

        except Exception as e:
            logger.exception(f"Tool task {task.token} failed: {e}")
            await self.fail_operation(task.token, str(e))

    async def start_task(
        self,
        token: str,
        tool_name: str,
        arguments: dict[str, Any],
        request_context: RequestContext[ServerSession, Any, Any],
    ) -> None:
        """Enqueue an async task for execution."""
        await self.broker.enqueue_task(token, tool_name, arguments, request_context)

    async def create_operation(
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
        await self.store.store_operation(operation)
        logger.info(f"Created async operation {token} for tool '{tool_name}'")
        return operation

    async def get_operation(self, token: str) -> ServerAsyncOperation | None:
        """Get operation by token."""
        return await self.store.get_operation(token)

    async def mark_working(self, token: str) -> bool:
        """Mark operation as working."""
        return await self.store.update_status(token, "working")

    async def complete_operation(self, token: str, result: types.CallToolResult) -> bool:
        """Complete operation with result."""
        success = await self.store.complete_operation_with_result(token, result)
        if success:
            await self.broker.complete_task(token)
            logger.info(f"Async operation {token} completed successfully")
        return success

    async def fail_operation(self, token: str, error: str) -> bool:
        """Fail operation with error."""
        success = await self.store.fail_operation_with_error(token, error)
        if success:
            await self.broker.complete_task(token)
            logger.info(f"Async operation {token} failed: {error}")
        return success

    async def cancel_operation(self, token: str) -> bool:
        """Cancel operation."""
        operation = await self.store.get_operation(token)
        if not operation or operation.status in ("completed", "failed", "canceled"):
            return False

        # Create new operation with updated fields instead of mutating
        cancelled_operation = ServerAsyncOperation(
            token=operation.token,
            tool_name=operation.tool_name,
            arguments=operation.arguments,
            status="canceled",
            created_at=operation.created_at,
            keep_alive=operation.keep_alive,
            resolved_at=time.time(),
            session_id=operation.session_id,
            result=operation.result,
            error=operation.error,
        )
        await self.store.store_operation(cancelled_operation)
        await self.broker.complete_task(token)  # Clean up from broker
        logger.info(f"Async operation {token} was cancelled")
        return True

    async def mark_input_required(self, token: str) -> bool:
        """Mark operation as requiring input."""
        operation = await self.store.get_operation(token)
        if not operation or operation.status not in ("submitted", "working"):
            return False

        await self.store.update_status(token, "input_required")
        return True

    async def mark_input_completed(self, token: str) -> bool:
        """Mark input as completed, transitioning back to working."""
        operation = await self.store.get_operation(token)
        if not operation or operation.status != "input_required":
            return False

        await self.store.update_status(token, "working")
        return True

    async def get_operation_result(self, token: str) -> types.CallToolResult | None:
        """Get result for completed operation."""
        operation = await self.store.get_operation(token)
        if not operation or operation.status != "completed":
            return None
        return operation.result

    async def cleanup_expired(self) -> int:
        """Remove expired operations and return count."""
        return await self.store.cleanup_expired()


class InMemoryAsyncOperationStore(AsyncOperationStore):
    """In-memory implementation of AsyncOperationStore."""

    def __init__(self):
        self._operations: dict[str, ServerAsyncOperation] = {}

    async def get_operation(self, token: str) -> ServerAsyncOperation | None:
        """Get operation by token."""
        return self._operations.get(token)

    async def store_operation(self, operation: ServerAsyncOperation) -> None:
        """Store an operation."""
        self._operations[operation.token] = operation

    async def update_status(self, token: str, status: AsyncOperationStatus) -> bool:
        """Update operation status."""
        operation = self._operations.get(token)
        if not operation:
            return False

        # Don't allow transitions from terminal states
        if operation.is_terminal:
            return False

        operation.status = status
        if status in ("completed", "failed", "canceled"):
            operation.resolved_at = time.time()
        return True

    async def complete_operation_with_result(self, token: str, result: types.CallToolResult) -> bool:
        """Complete operation with result."""
        operation = self._operations.get(token)
        if not operation or operation.is_terminal:
            return False

        operation.status = "completed"
        operation.result = result
        operation.resolved_at = time.time()
        return True

    async def fail_operation_with_error(self, token: str, error: str) -> bool:
        """Fail operation with error."""
        operation = self._operations.get(token)
        if not operation or operation.is_terminal:
            return False

        operation.status = "failed"
        operation.error = error
        operation.resolved_at = time.time()
        return True

    async def cleanup_expired(self) -> int:
        """Remove expired operations and return count."""
        expired_tokens = [token for token, op in self._operations.items() if op.is_expired]
        for token in expired_tokens:
            del self._operations[token]
        return len(expired_tokens)


class InMemoryAsyncOperationBroker(AsyncOperationBroker):
    """In-memory implementation of AsyncOperationBroker."""

    def __init__(self):
        self._task_queue: deque[PendingAsyncTask] = deque()

    async def enqueue_task(
        self,
        token: str,
        tool_name: str,
        arguments: dict[str, Any],
        request_context: RequestContext[ServerSession, Any, Any],
    ) -> None:
        """Enqueue a task for execution."""
        task = PendingAsyncTask(token=token, tool_name=tool_name, arguments=arguments, request_context=request_context)
        self._task_queue.append(task)

    async def get_pending_tasks(self) -> list[PendingAsyncTask]:
        """Get all pending tasks without clearing them."""
        return list(self._task_queue)

    async def acknowledge_task(self, token: str) -> None:
        """Acknowledge that a task has been dispatched."""
        # Remove the task from the queue
        self._task_queue = deque(task for task in self._task_queue if task.token != token)

    async def complete_task(self, token: str) -> None:
        """Remove a completed task from persistent storage."""
        # For in-memory broker, this is the same as acknowledge
        self._task_queue = deque(task for task in self._task_queue if task.token != token)
