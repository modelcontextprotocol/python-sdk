# server_session_store.py (oder neben StatefulMCP)
from typing import Any, Mapping
import copy
import anyio

class ServerSessionData:
    """Thread-safe key-value store scoped to a server session.

    Methods are async to coordinate access with a lock. Values are user-defined.
    """
    def __init__(self, initial: Mapping[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = dict(initial or {})
        self._lock = anyio.Lock()

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            self._data[key] = value

    async def get(self, key: str, default: Any = None) -> Any:
        async with self._lock:
            return self._data.get(key, default)

    async def update(self, mapping: Mapping[str, Any] | None = None, /, **kwargs: Any) -> None:
        async with self._lock:
            if mapping:
                self._data.update(mapping)
            if kwargs:
                self._data.update(kwargs)

    async def pop(self, key: str, default: Any = None) -> Any:
        async with self._lock:
            return self._data.pop(key, default)

    async def clear(self) -> None:
        async with self._lock:
            self._data.clear()

    async def reset(self) -> None:
        await self.clear()

    async def keys(self) -> list[str]:
        async with self._lock:
            return list(self._data.keys())

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return copy.deepcopy(self._data)  # read-only copy
