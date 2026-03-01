"""Companion examples for src/mcp/server/experimental/task_support.py docstrings."""

from __future__ import annotations

from typing import Any

from mcp.server.lowlevel.server import Server
from mcp.shared.experimental.tasks.message_queue import TaskMessageQueue
from mcp.shared.experimental.tasks.store import TaskStore


# Stubs for undefined references in examples
class RedisTaskStore(TaskStore):  # type: ignore[abstract]
    def __init__(self, redis_url: str) -> None: ...


class RedisTaskMessageQueue(TaskMessageQueue):  # type: ignore[abstract]
    def __init__(self, redis_url: str) -> None: ...


def TaskSupport_simple(server: Server[Any]) -> None:
    # region TaskSupport_simple
    server.experimental.enable_tasks()
    # endregion TaskSupport_simple


def TaskSupport_custom(server: Server[Any], redis_url: str) -> None:
    # region TaskSupport_custom
    server.experimental.enable_tasks(
        store=RedisTaskStore(redis_url),
        queue=RedisTaskMessageQueue(redis_url),
    )
    # endregion TaskSupport_custom
