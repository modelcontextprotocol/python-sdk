"""Client-side response caching primitives (SEP-2549, protocol revision 2026-07-28)."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

import anyio
import anyio.lowlevel
from mcp_types import (
    CacheableResult,
    PromptListChangedNotification,
    ResourceListChangedNotification,
    ResourceUpdatedNotification,
    ServerNotification,
    ToolListChangedNotification,
)
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

__all__ = [
    "MAX_TTL_MS",
    "CacheConfig",
    "CacheEntry",
    "CacheKey",
    "CacheMode",
    "InMemoryResponseCacheStore",
    "ResponseCacheStore",
]

logger = logging.getLogger(__name__)

CacheMode = Literal["use", "refresh", "bypass"]
"""Per-call cache behavior: `"use"` serves and stores, `"refresh"` stores
without serving, `"bypass"` skips the cache entirely."""

MAX_TTL_MS: Final[int] = 24 * 60 * 60 * 1000
"""Cap on any entry's time-to-live (24 hours, in milliseconds); larger `ttlMs` values are clamped down."""


@dataclass(frozen=True, slots=True)
class CacheKey:
    """Identity of one cached response; compare as the field tuple, never a flattened string (collision hazard)."""

    method: str

    params_key: str = ""
    """Result-affecting params discriminator: the uri for `resources/read`, `""` for the list methods."""

    partition: str = ""
    """Coordinator-computed arm identifier; opaque to stores."""


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """One cached response with its freshness and sharing metadata."""

    value: Any
    """The cached result; the SDK deep-copies on write and on serve, so a store may hold it as-is."""

    scope: Literal["public", "private"]
    """Server-asserted `cacheScope`: only `"public"` entries may be shared across authorization contexts."""

    expires_at: float | None
    """Epoch seconds after which the entry is stale; `None` is never fresh."""


class ResponseCacheStore(Protocol):
    """Storage contract for the client response cache.

    Each `Client` calls its store from a single event loop; per-operation
    atomicity is the implementation's responsibility. Operations may raise -
    the SDK degrades to a miss rather than failing the call. A serializing
    store must round-trip `value` back to the result model object (a
    wrong-shape entry is a miss, never an error). A lookup may issue two
    sequential `get` calls (private arm, then public).
    """

    async def get(self, key: CacheKey) -> CacheEntry | None: ...

    async def set(self, key: CacheKey, entry: CacheEntry) -> None: ...

    async def delete(self, key: CacheKey) -> None: ...

    async def clear(self) -> None: ...


@dataclass(frozen=True, slots=True)
class CacheConfig:
    """Configuration for a `Client`'s response cache.

    Raises:
        ValueError: On a custom `store` without `partition`, an empty `target_id`, or a negative `default_ttl_ms`.
    """

    store: ResponseCacheStore | None = None
    """Backing store; `None` means a per-client `InMemoryResponseCacheStore`.
    A custom store requires an explicit `partition`."""

    partition: str = ""
    """Authorization-context identifier isolating `"private"`-scoped entries
    within a shared store. Derive it from a verified credential - never from
    request-supplied data or the server URL. Fixed for the `Client`'s
    lifetime: construct a new `Client` when the principal changes."""

    target_id: str | None = None
    """Server-identity override for custom transports and proxies where the
    SDK cannot derive one from a URL; must be non-empty when provided."""

    default_ttl_ms: int = 0
    """TTL in milliseconds for results carrying no `ttlMs` hint; the default `0` leaves them uncached."""

    clock: Callable[[], float] = time.time
    """Wall-clock source returning epoch seconds; injectable for expiry tests."""

    share_public: bool = False
    """Serve server-marked `"public"` entries across every partition in the store.

    WARNING: this trusts the server's `"public"` classification for every
    principal sharing the store - a mislabeled response leaks across tenants.
    Constructor-level only: the per-call `cache_mode` can never widen sharing."""

    def __post_init__(self) -> None:
        if self.store is not None and not self.partition:
            raise ValueError("a custom store requires an explicit partition")
        if self.target_id == "":
            raise ValueError("target_id must be a non-empty string or omitted")
        if self.default_ttl_ms < 0:
            raise ValueError(f"default_ttl_ms must be >= 0, got {self.default_ttl_ms}")


class InMemoryResponseCacheStore:
    """Default in-process `ResponseCacheStore`.

    Method bodies are synchronous, so concurrent tasks never observe a torn
    write. `max_entries` caps the whole store, evicting least-recently-used
    at the cap (`0` disables it); `get` and `set` both refresh recency, so a
    hot entry survives churn from other keys.

    Raises:
        ValueError: If `max_entries` is negative.
    """

    def __init__(self, *, max_entries: int = 1024) -> None:
        if max_entries < 0:
            raise ValueError(f"max_entries must be >= 0, got {max_entries}")
        self._max_entries = max_entries
        self._entries: dict[CacheKey, CacheEntry] = {}

    async def get(self, key: CacheKey) -> CacheEntry | None:
        entry = self._entries.get(key)
        if entry is not None:
            # Pop-and-reinsert moves the key to the back: the dict's insertion order is the LRU ledger.
            self._entries[key] = self._entries.pop(key)
        return entry

    async def set(self, key: CacheKey, entry: CacheEntry) -> None:
        self._entries.pop(key, None)
        self._entries[key] = entry
        if self._max_entries and len(self._entries) > self._max_entries:
            del self._entries[next(iter(self._entries))]

    async def delete(self, key: CacheKey) -> None:
        self._entries.pop(key, None)

    async def clear(self) -> None:
        self._entries.clear()


_GENERATION_MAP_CAP: Final[int] = 4096
"""Cap on the generation map; at the cap the oldest key's eviction-race guard is dropped (FIFO)."""

_STORE_CLEANUP_TIMEOUT: Final[float] = 5
"""Bound for must-complete store cleanup deletes (mirrors the dispatcher's final-write bound);
a wedged store delete must not hold client teardown uncancellably."""


class ClientResponseCache:
    """Coordinates the `Client` caching verbs with a `ResponseCacheStore`: keys, era gate, TTL/scope, eviction."""

    def __init__(
        self,
        *,
        store: ResponseCacheStore,
        partition: str,
        arm_id: str,
        default_ttl_ms: int,
        clock: Callable[[], float],
        share_public: bool,
        negotiated_version: Callable[[], str | None],
        generation_map_cap: int = _GENERATION_MAP_CAP,
        store_cleanup_timeout: float = _STORE_CLEANUP_TIMEOUT,
    ) -> None:
        self._store = store
        self._partition = partition
        self._arm_id = arm_id
        self._share_public = share_public
        self._default_ttl_ms = default_ttl_ms
        self._clock = clock
        self._negotiated_version = negotiated_version
        # A key is eviction-race-guarded iff registered here.
        self._generations: dict[tuple[str, str], int] = {}
        self._generation_map_cap = generation_map_cap
        self._store_cleanup_timeout = store_cleanup_timeout
        self._warned_store_ops: set[str] = set()

    def _arm(self, scope: Literal["public", "private"]) -> str:
        # JSON arrays so crafted arm_id/partition values cannot collide across field boundaries.
        # The negotiated version era-scopes every arm: a session never serves an entry written
        # under a different protocol era (its content differs - sieve-stripped fields, header
        # filtering). Every caller runs post-connect; were that ever untrue, the supplier's
        # None still partitions harmlessly.
        fields: list[str | None] = [scope, self._negotiated_version(), self._arm_id]
        if scope == "private" or not self._share_public:
            fields.append(self._partition)
        return json.dumps(fields)

    async def read(self, method: str, params_key: str) -> CacheableResult | None:
        """Serve a fresh entry for the key, or `None`; the served result is a deep copy."""
        # A hit completes without any other yielding await, so checkpoint here: a poll
        # loop over a fresh entry must not starve spawned tasks (eviction dispatch).
        await anyio.lowlevel.checkpoint()
        # A wrong-shape entry raises as late as the copy, so the boundary wraps the whole read path.
        try:
            entry = await self._get_fresh(CacheKey(method, params_key, self._arm("private")))
            if entry is None:
                # After a scope flip, a stale private entry must not shadow a fresh public one.
                entry = await self._get_fresh(CacheKey(method, params_key, self._arm("public")))
                if entry is not None and entry.scope != "public":
                    # Never serve an entry the server scoped "private" out of the shared arm.
                    entry = None
            copied: CacheableResult | None = None if entry is None else entry.value.model_copy(deep=True)
        except Exception:  # boundary around user store code: any read-path failure is a miss, never a failed call
            self._warn_store_failure("get")
            return None
        self._warned_store_ops.discard("get")
        return copied

    async def _get_fresh(self, key: CacheKey) -> CacheEntry | None:
        entry = await self._store.get(key)
        if entry is None or entry.expires_at is None or entry.expires_at <= self._clock():
            return None
        return entry

    def capture(self, method: str, params_key: str) -> int:
        """Register the key for eviction-race detection before the fetch; `write` takes the returned generation."""
        gen_key = (method, params_key)
        if gen_key not in self._generations:
            if len(self._generations) >= self._generation_map_cap:
                # FIFO overflow: the dropped key's race guard degrades to the accepted co-tenant class.
                del self._generations[next(iter(self._generations))]
            self._generations[gen_key] = 0
        return self._generations[gen_key]

    async def write(
        self,
        method: str,
        params_key: str,
        result: CacheableResult,
        gen_at_capture: int,
        mode: Literal["use", "refresh"],
    ) -> None:
        """Store a fetched result under the arm its resolved scope selects."""
        gen_key = (method, params_key)
        if self._generation_moved(gen_key, gen_at_capture):
            return  # the key was evicted while the fetch was in flight
        ttl_ms, scope = self._resolve(result)
        private_key = CacheKey(method, params_key, self._arm("private"))
        public_key = CacheKey(method, params_key, self._arm("public"))
        if ttl_ms <= 0:
            if mode == "refresh":
                # The refetch superseded the warm entry, which a cancellation must not leave serving.
                await self._cleanup_delete(private_key, public_key)
            return
        own, opposite = (public_key, private_key) if scope == "public" else (private_key, public_key)
        # Opposite arm first: a failed delete aborts before the set - never two arms answering for one key.
        if not await self._delete(opposite):
            # The own arm's entry is superseded too: best-effort delete, degrading to a full miss.
            await self._cleanup_delete(own)
            return
        entry = CacheEntry(value=result.model_copy(deep=True), scope=scope, expires_at=self._clock() + ttl_ms / 1000)
        try:
            if not await self._set(own, entry):
                # The fetch superseded any pre-existing own-arm entry, and the failed set
                # left it in place: purge it (mirrors the opposite-arm-failure path).
                await self._cleanup_delete(own)
        finally:
            # An eviction can land while the set commits - even when the await
            # is cancelled - so re-check on every exit; the delete must complete
            # so the pending cancellation cannot resurrect the evicted entry.
            if self._generation_moved(gen_key, gen_at_capture):
                await self._cleanup_delete(own)

    async def evict_method(self, method: str) -> None:
        """Evict the method's cursor-less entry."""
        await self.evict_key(method, "")

    async def evict_key(self, method: str, params_key: str) -> None:
        """Evict one key from both arms.

        Only the current era's arms are touched; other-era entries in a persistent store age out by TTL.
        """
        gen_key = (method, params_key)
        # Bump first so an in-flight fetch cannot write the evicted entry back.
        # Unregistered keys skip the bump (uris must not grow the map) but not
        # the deletes - a persistent store may hold uncaptured entries.
        if gen_key in self._generations:
            self._generations[gen_key] += 1
        # Must complete: a cancellation between the deletes would leave one arm serving the evicted entry.
        await self._cleanup_delete(
            CacheKey(method, params_key, self._arm("private")),
            CacheKey(method, params_key, self._arm("public")),
        )

    async def evict_for_notification(self, notification: ServerNotification) -> None:
        """Map a server notification to the entries it makes stale.

        Eviction is eventual (spawned-task dispatch): the generation bump closes
        the write-back race; a racing read may briefly serve the old entry.
        """
        match notification:
            case ToolListChangedNotification():
                await self.evict_method("tools/list")
            case PromptListChangedNotification():
                await self.evict_method("prompts/list")
            case ResourceListChangedNotification():
                # Templates enumerate the same changed resource space.
                await self.evict_method("resources/list")
                await self.evict_method("resources/templates/list")
            case ResourceUpdatedNotification():
                await self.evict_key("resources/read", notification.params.uri)
            case _:
                pass

    def _resolve(self, result: CacheableResult) -> tuple[int, Literal["public", "private"]]:
        # A legacy peer can also put `ttlMs`/`cacheScope` keys on the wire, so
        # wire presence is not a peer-era signal - hints count only when modern.
        modern = self._negotiated_version() in MODERN_PROTOCOL_VERSIONS
        if modern and "ttl_ms" in result.model_fields_set:
            # An explicit `ttlMs: 0` stays 0, and negatives are unconstructible
            # upstream (model ge=0, parse-seam floor) - only the cap applies.
            ttl_ms = result.ttl_ms
        else:
            ttl_ms = self._default_ttl_ms
        scope: Literal["public", "private"] = "public" if modern and result.cache_scope == "public" else "private"
        return min(ttl_ms, MAX_TTL_MS), scope

    def _generation_moved(self, gen_key: tuple[str, str], gen_at_capture: int) -> bool:
        # A FIFO-dropped key fails open (the accepted co-tenant race) rather than discarding the fetch.
        return self._generations.get(gen_key, gen_at_capture) != gen_at_capture

    async def _set(self, key: CacheKey, entry: CacheEntry) -> bool:
        try:
            await self._store.set(key, entry)
        except Exception:  # boundary around user store code: nothing cached, the fetch already succeeded
            self._warn_store_failure("set")
            return False
        self._warned_store_ops.discard("set")
        return True

    async def _cleanup_delete(self, *keys: CacheKey) -> None:
        # Must-complete cleanup: shielded so a pending cancellation cannot skip the deletes,
        # bounded so a wedged store delete cannot hold client teardown uncancellably.
        with anyio.move_on_after(self._store_cleanup_timeout, shield=True) as scope:
            for key in keys:
                await self._delete(key)
        if scope.cancelled_caught:
            logger.warning("Response cache store delete timed out; the entry will age out by TTL")

    async def _delete(self, key: CacheKey) -> bool:
        try:
            await self._store.delete(key)
        except Exception:  # boundary around user store code: callers decide whether a failed delete aborts
            self._warn_store_failure("delete")
            return False
        self._warned_store_ops.discard("delete")
        return True

    def _warn_store_failure(self, kind: Literal["get", "set", "delete"]) -> None:
        # One warning per failure burst, per op kind; re-armed only when that
        # same kind succeeds, so a healthy delete cannot re-arm a broken set.
        if kind not in self._warned_store_ops:
            self._warned_store_ops.add(kind)
            logger.warning("Response cache store operation failed; continuing without the cache", exc_info=True)
