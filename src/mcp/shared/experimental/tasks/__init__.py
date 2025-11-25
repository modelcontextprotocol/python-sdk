"""
Experimental task management for MCP.

This module provides:
- TaskStore: Abstract interface for task state storage
- TaskContext: Context object for task work to interact with state/notifications
- InMemoryTaskStore: Reference implementation for testing/development
- TaskMessageQueue: FIFO queue for task messages delivered via tasks/result
- InMemoryTaskMessageQueue: Reference implementation for message queue
- Helper functions: run_task, is_terminal, create_task_state, generate_task_id, cancel_task

Architecture:
- TaskStore is pure storage - it doesn't know about execution
- TaskMessageQueue stores messages to be delivered via tasks/result
- TaskContext wraps store + session, providing a clean API for task work
- run_task is optional convenience for spawning in-process tasks

WARNING: These APIs are experimental and may change without notice.
"""

from mcp.shared.experimental.tasks.context import TaskContext
from mcp.shared.experimental.tasks.helpers import (
    cancel_task,
    create_task_state,
    generate_task_id,
    is_terminal,
    run_task,
    task_execution,
)
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.shared.experimental.tasks.message_queue import (
    InMemoryTaskMessageQueue,
    QueuedMessage,
    TaskMessageQueue,
)
from mcp.shared.experimental.tasks.resolver import Resolver
from mcp.shared.experimental.tasks.result_handler import TaskResultHandler
from mcp.shared.experimental.tasks.store import TaskStore
from mcp.shared.experimental.tasks.task_session import RELATED_TASK_METADATA_KEY, TaskSession

__all__ = [
    "TaskStore",
    "TaskContext",
    "TaskSession",
    "TaskResultHandler",
    "Resolver",
    "InMemoryTaskStore",
    "TaskMessageQueue",
    "InMemoryTaskMessageQueue",
    "QueuedMessage",
    "RELATED_TASK_METADATA_KEY",
    "run_task",
    "task_execution",
    "is_terminal",
    "create_task_state",
    "generate_task_id",
    "cancel_task",
]
