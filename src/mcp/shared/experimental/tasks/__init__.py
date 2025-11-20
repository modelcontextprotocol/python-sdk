"""
Experimental task management for MCP.

This module provides:
- TaskStore: Abstract interface for task state storage
- TaskContext: Context object for task work to interact with state/notifications
- InMemoryTaskStore: Reference implementation for testing/development
- Helper functions: run_task, is_terminal, create_task_state, generate_task_id

Architecture:
- TaskStore is pure storage - it doesn't know about execution
- TaskContext wraps store + session, providing a clean API for task work
- run_task is optional convenience for spawning in-process tasks

WARNING: These APIs are experimental and may change without notice.
"""

from mcp.shared.experimental.tasks.context import TaskContext
from mcp.shared.experimental.tasks.helpers import (
    create_task_state,
    generate_task_id,
    is_terminal,
    run_task,
    task_execution,
)
from mcp.shared.experimental.tasks.in_memory_task_store import InMemoryTaskStore
from mcp.shared.experimental.tasks.store import TaskStore

__all__ = [
    "TaskStore",
    "TaskContext",
    "InMemoryTaskStore",
    "run_task",
    "task_execution",
    "is_terminal",
    "create_task_state",
    "generate_task_id",
]
