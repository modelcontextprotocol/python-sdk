"""Client-side response caching primitives (SEP-2549, protocol revision 2026-07-28).

Results for the cacheable methods carry `ttlMs`/`cacheScope` freshness hints;
the client honors them through a response cache configured with `CacheConfig`.
This module defines the configuration, the store contract (`ResponseCacheStore`
keyed by `CacheKey`, holding `CacheEntry` values), and the default in-process
store. Wiring into `Client` lives in `mcp.client.client`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

__all__ = [
    "MAX_TTL_MS",
    "CacheConfig",
    "CacheEntry",
    "CacheKey",
    "CacheMode",
    "InMemoryResponseCacheStore",
    "ResponseCacheStore",
]

CacheMode = Literal["use", "refresh", "bypass"]
"""Per-call cache behavior: `"use"` serves fresh entries and stores fetches,
`"refresh"` skips the read but stores the fetch, `"bypass"` touches the cache
not at all."""

MAX_TTL_MS: Final[int] = 24 * 60 * 60 * 1000
"""Upper bound on any entry's time-to-live (24 hours, in milliseconds): a
server-provided or configured `ttlMs` above it is clamped down, bounding how
long a stale entry can be served."""


@dataclass(frozen=True, slots=True)
class CacheKey:
    """Identity of one cached response.

    Stores MUST compare keys as the `(method, params_key, partition)` field
    tuple - never by flattening the fields into one delimited string, which
    lets crafted values collide across field boundaries.
    """

    method: str
    """The request method, e.g. `"tools/list"`."""

    params_key: str = ""
    """Result-affecting params discriminator: the uri for `resources/read`,
    `""` for the list methods (only cursor-less calls participate in caching)."""

    partition: str = ""
    """Coordinator-computed arm identifier; opaque to stores."""


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """One cached response with its freshness and sharing metadata."""

    value: Any
    """The cached result. The SDK deep-copies it on write and on serve, so a
    store may hold the object as-is."""

    scope: Literal["public", "private"]
    """The server-asserted `cacheScope`: whether the entry may be shared
    across authorization contexts (`"public"`) or only reused within the one
    that produced it (`"private"`)."""

    expires_at: float | None
    """Epoch seconds after which the entry is stale; `None` is never fresh."""


class ResponseCacheStore(Protocol):
    """Storage contract for the client response cache.

    Keys MUST be compared as the `(method, params_key, partition)` field tuple -
    no delimiter-based flattening (collision hazard). Each `Client` calls its
    store from a single event loop; cross-loop sharing and per-operation
    atomicity are the implementation's responsibility. Operations may raise;
    the SDK degrades per its error discipline (a failing store never fails a
    successful fetch).
    """

    async def get(self, key: CacheKey) -> CacheEntry | None: ...

    async def set(self, key: CacheKey, entry: CacheEntry) -> None: ...

    async def delete(self, key: CacheKey) -> None: ...

    async def clear(self) -> None: ...


@dataclass(frozen=True, slots=True)
class CacheConfig:
    """Configuration for a `Client`'s response cache.

    Raises:
        ValueError: If a custom `store` is given without a `partition`, or if
            `default_ttl_ms` is negative.
    """

    store: ResponseCacheStore | None = None
    """Backing store; `None` means a store-per-client `InMemoryResponseCacheStore`.
    A custom store requires an explicit `partition`."""

    partition: str = ""
    """Authorization-context identifier isolating `"private"`-scoped entries
    within a shared store.

    Derive it from a verified credential (e.g. a validated token's subject) -
    never from request-supplied data, and never from the server URL (server
    identity is a separate key axis). The SDK is a library with no
    authentication of its own: whoever constructs the `CacheConfig` - the
    deployment, not the tenant - is the trust anchor. Multi-tenant gateways
    mint one `CacheConfig` per authenticated principal.
    """

    target_id: str | None = None
    """Explicit server-identity override, for custom transports and proxies
    where the SDK cannot derive an identity from a server URL."""

    default_ttl_ms: int = 0
    """Time-to-live, in milliseconds, applied to results that carry no `ttlMs`
    hint. The default `0` leaves hint-less results uncached."""

    clock: Callable[[], float] = time.time
    """Wall-clock source returning epoch seconds; injectable so expiry tests
    need no sleeping."""

    share_public: bool = False
    """Serve entries the server marked `cacheScope: "public"` across every
    partition using the store, instead of only within the partition that
    fetched them.

    WARNING: enabling this trusts the server's public classification for every
    principal sharing the store - a server that stamps `"public"` on
    per-tenant data (by bug or by malice) leaks one tenant's response to the
    others. It is deliberately constructor-level only, set once by the
    operator: the per-call `cache_mode` kwarg can narrow caching but can never
    widen sharing.
    """

    def __post_init__(self) -> None:
        if self.store is not None and not self.partition:
            raise ValueError("a custom store requires an explicit partition")
        if self.default_ttl_ms < 0:
            raise ValueError(f"default_ttl_ms must be >= 0, got {self.default_ttl_ms}")


class InMemoryResponseCacheStore:
    """Default in-process `ResponseCacheStore`.

    Method bodies are synchronous (no awaits), so each operation completes
    without an event-loop checkpoint and concurrent tasks can never observe a
    torn write. Memory is bounded: the methods other than `resources/read`
    form a small closed set of keys, and `max_read_entries` caps the
    `resources/read` entries (one per uri) - storing a new read key at the cap
    evicts the oldest read key, first-in-first-out. `0` disables the cap.

    Raises:
        ValueError: If `max_read_entries` is negative.
    """

    def __init__(self, *, max_read_entries: int = 512) -> None:
        if max_read_entries < 0:
            raise ValueError(f"max_read_entries must be >= 0, got {max_read_entries}")
        self._max_read_entries = max_read_entries
        self._entries: dict[CacheKey, CacheEntry] = {}

    async def get(self, key: CacheKey) -> CacheEntry | None:
        return self._entries.get(key)

    async def set(self, key: CacheKey, entry: CacheEntry) -> None:
        if self._max_read_entries and key.method == "resources/read" and key not in self._entries:
            # dict preserves insertion order and replacement keeps position, so
            # the dict itself is the FIFO ledger - no parallel structure to drift.
            read_keys = [k for k in self._entries if k.method == "resources/read"]
            if len(read_keys) >= self._max_read_entries:
                del self._entries[read_keys[0]]
        self._entries[key] = entry

    async def delete(self, key: CacheKey) -> None:
        self._entries.pop(key, None)

    async def clear(self) -> None:
        self._entries.clear()
