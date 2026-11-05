from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio


class KeyedLocks:
    """One lock per key, dropped once nobody holds or awaits it."""

    def __init__(self) -> None:
        self._locks: dict[str, anyio.Lock] = {}

    @asynccontextmanager
    async def __call__(self, key: str) -> AsyncIterator[None]:
        lock = self._locks.setdefault(key, anyio.Lock())
        try:
            async with lock:
                yield
        finally:
            if not lock.locked() and not lock.statistics().tasks_waiting:
                del self._locks[key]
