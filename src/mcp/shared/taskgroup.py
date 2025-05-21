from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, TypeVar

import anyio

_T = TypeVar("_T")

class _AsyncioCancelScope:
    def __init__(self, tasks: set[asyncio.Task[Any]]):
        self._tasks = tasks

    def cancel(self) -> None:
        for task in list(self._tasks):
            task.cancel()

class CompatTaskGroup(AbstractAsyncContextManager):
    """Minimal compatibility layer mimicking ``anyio.TaskGroup``."""

    def __init__(self) -> None:
        self._use_asyncio = sys.version_info >= (3, 11)
        if self._use_asyncio:
            self._tg = asyncio.TaskGroup()
            self._tasks: set[asyncio.Task[Any]] = set()
            self.cancel_scope = _AsyncioCancelScope(self._tasks)
        else:
            self._tg = anyio.create_task_group()
            self.cancel_scope = self._tg.cancel_scope  # type: ignore[attr-defined]

    async def __aenter__(self) -> CompatTaskGroup:
        await self._tg.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool | None:
        return await self._tg.__aexit__(exc_type, exc, tb)

    def start_soon(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        name: Any | None = None,
    ) -> None:
        if self._use_asyncio:
            task = self._tg.create_task(func(*args))
            self._tasks.add(task)
        else:
            self._tg.start_soon(func, *args, name=name)

    async def start(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        name: Any | None = None,
    ) -> Any:
        if self._use_asyncio:
            fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()

            async def runner() -> None:
                try:
                    result = await func(*args, task_status=fut)
                    if not fut.done():
                        fut.set_result(result)
                except BaseException as exc:
                    if not fut.done():
                        fut.set_exception(exc)
                    raise

            task = self._tg.create_task(runner())
            self._tasks.add(task)
            return await fut
        else:
            return await self._tg.start(func, *args, name=name)
