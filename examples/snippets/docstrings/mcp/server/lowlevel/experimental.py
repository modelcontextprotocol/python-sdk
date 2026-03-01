"""Companion examples for src/mcp/server/lowlevel/experimental.py docstrings."""

from __future__ import annotations

from typing import Any

from mcp.server.lowlevel.server import Server
from mcp.shared.experimental.tasks.message_queue import TaskMessageQueue
from mcp.shared.experimental.tasks.store import TaskStore


class RedisTaskStore(TaskStore):  # type: ignore[abstract]
    def __init__(self, redis_url: str) -> None: ...


class RedisTaskMessageQueue(TaskMessageQueue):  # type: ignore[abstract]
    def __init__(self, redis_url: str) -> None: ...


def ExperimentalHandlers_enable_tasks_simple(server: Server[Any]) -> None:
    # region ExperimentalHandlers_enable_tasks_simple
    server.experimental.enable_tasks()
    # endregion ExperimentalHandlers_enable_tasks_simple


def ExperimentalHandlers_enable_tasks_custom(server: Server[Any], redis_url: str) -> None:
    # region ExperimentalHandlers_enable_tasks_custom
    server.experimental.enable_tasks(
        store=RedisTaskStore(redis_url),
        queue=RedisTaskMessageQueue(redis_url),
    )
    # endregion ExperimentalHandlers_enable_tasks_custom
