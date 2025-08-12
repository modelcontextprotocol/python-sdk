from __future__ import annotations

from typing import Any, Mapping
import copy
import threading

class ServerSessionData:
    """Thread-safe key-value store scoped to one server session.

    Design:
      - **Synchronous core** guarded by a threading.RLock → usable from sync and async code.
      - **Async convenience wrappers** (`a*` methods) simply call the sync core.
      - Very short critical sections (dict ops), so using sync methods from async code is fine.
    """

    def __init__(self, initial: Mapping[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = dict(initial or {})
        self._lock = threading.RLock()

    # ----- synchronous API (primary) -----

    def set(self, key: str, value: Any) -> None:
        """Set a value (thread-safe)."""
        with self._lock:
            self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value (thread-safe)."""
        with self._lock:
            return self._data.get(key, default)

    def update(self, mapping: Mapping[str, Any] | None = None, /, **kwargs: Any) -> None:
        """Update multiple keys (thread-safe)."""
        with self._lock:
            if mapping:
                self._data.update(mapping)
            if kwargs:
                self._data.update(kwargs)

    def pop(self, key: str, default: Any = None) -> Any:
        """Pop a value (thread-safe)."""
        with self._lock:
            return self._data.pop(key, default)

    def clear(self) -> None:
        """Clear all values (thread-safe)."""
        with self._lock:
            self._data.clear()

    def reset(self) -> None:
        """Alias for clear()."""
        self.clear()

    def keys(self) -> list[str]:
        """List keys (thread-safe snapshot)."""
        with self._lock:
            return list(self._data.keys())

    def snapshot(self) -> dict[str, Any]:
        """Deep copy of all data (thread-safe)."""
        with self._lock:
            return copy.deepcopy(self._data)

    # ----- async convenience wrappers -----

    async def aset(self, key: str, value: Any) -> None:
        self.set(key, value)

    async def aget(self, key: str, default: Any = None) -> Any:
        return self.get(key, default)

    async def aupdate(self, mapping: Mapping[str, Any] | None = None, /, **kwargs: Any) -> None:
        self.update(mapping, **kwargs)

    async def apop(self, key: str, default: Any = None) -> Any:
        return self.pop(key, default)

    async def aclear(self) -> None:
        self.clear()

    async def areset(self) -> None:
        self.reset()

    async def akeys(self) -> list[str]:
        return self.keys()

    async def asnapshot(self) -> dict[str, Any]:
        return self.snapshot()
