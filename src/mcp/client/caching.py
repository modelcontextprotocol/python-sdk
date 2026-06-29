"""Client-side response caching primitives (SEP-2549, protocol revision 2026-07-28).

Results for the cacheable methods carry `ttlMs`/`cacheScope` freshness hints;
the client honors them through a response cache configured with `CacheConfig`.
This module defines the configuration, the store contract (`ResponseCacheStore`
keyed by `CacheKey`, holding `CacheEntry` values), and the default in-process
store. Wiring into `Client` lives in `mcp.client.client`.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

import anyio
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

    A store that serializes entries (any cross-process store must) is
    responsible for round-tripping them: `get` returns the entry as stored,
    with `value` still the result model object `set` received - the SDK has
    no rehydration hook to rebuild it from serialized data. An entry that
    comes back in the wrong shape (e.g. with a plain-dict value) degrades to
    a cache miss, never an error.
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


_GENERATION_MAP_CAP: Final[int] = 4096
"""Cap on the coordinator's eviction-race bookkeeping (the generation map).
At the cap, registering a new key drops the oldest one, degrading the dropped
key's race guard to the accepted co-tenant class."""


class ClientResponseCache:
    """Coordinator between the `Client` verbs and a `ResponseCacheStore`.

    Owns key construction (the scope arms), the era gate, TTL/scope
    resolution, eviction, and the store error discipline. `Client` mints one
    per instance; the caching verbs and the notification wrap are the only
    callers.
    """

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
    ) -> None:
        self._store = store
        self._default_ttl_ms = default_ttl_ms
        self._clock = clock
        self._negotiated_version = negotiated_version
        # Arms are JSON arrays so crafted arm_id/partition values cannot
        # collide across field boundaries. Private entries always carry the
        # partition; public entries do too unless the operator opted into
        # fleet-wide sharing of server-asserted-public results.
        self._private_arm = json.dumps(["private", arm_id, partition])
        self._public_arm = json.dumps(["public", arm_id] if share_public else ["public", arm_id, partition])
        # The generation map is the sole membership structure: a key is
        # race-guarded iff registered here.
        self._generations: dict[tuple[str, str], int] = {}
        self._generation_map_cap = generation_map_cap
        # Operation kinds ("get"/"set"/"delete") that warned and have not
        # succeeded since; membership suppresses repeat warnings for the kind.
        self._warned_store_ops: set[str] = set()

    async def read(self, method: str, params_key: str) -> CacheableResult | None:
        """Serve a fresh entry for the key, or `None`.

        Called only under `cache_mode="use"`; returns a deep copy so a served
        result never aliases the stored one.
        """
        # One boundary around the whole read path: a raising store `get` and
        # an entry rehydrated into the wrong shape (which raises only at the
        # freshness check or the copy) are the same "get" failure class -
        # warned once per burst, re-armed only by a fully successful read.
        try:
            entry = await self._get_fresh(CacheKey(method, params_key, self._private_arm))
            if entry is None:
                # Stale counts as a miss for fall-through too: after a server
                # scope flip (private -> public), a stale private leftover
                # must not shadow a fresh public entry.
                entry = await self._get_fresh(CacheKey(method, params_key, self._public_arm))
                if entry is not None and entry.scope != "public":
                    # The arm routes, the scope verifies: never serve an entry the
                    # server scoped "private" out of the shared arm, however it
                    # got there.
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
        """Register the key for eviction-race detection, before the fetch is
        sent; the matching `write` passes the returned generation back."""
        gen_key = (method, params_key)
        if gen_key not in self._generations:
            if len(self._generations) >= self._generation_map_cap:
                # FIFO overflow: drop the oldest key, degrading its race guard
                # to the accepted co-tenant class (an eviction racing that
                # key's in-flight fetch is no longer detected at write time).
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
        private_key = CacheKey(method, params_key, self._private_arm)
        public_key = CacheKey(method, params_key, self._public_arm)
        if ttl_ms <= 0:
            if mode == "refresh":
                # The refetch superseded whatever was cached; purge the warm
                # entry so it cannot be served again. Shielded: a cancellation
                # delivered between the two deletes would leave the opposite
                # arm warm for its full TTL.
                with anyio.CancelScope(shield=True):
                    await self._delete(private_key)
                    await self._delete(public_key)
            return
        own, opposite = (public_key, private_key) if scope == "public" else (private_key, public_key)
        # Opposite arm first: a failed (or cancelled) delete aborts before the
        # set, leaving a miss - never two arms answering for one key.
        if not await self._delete(opposite):
            return
        entry = CacheEntry(value=result.model_copy(deep=True), scope=scope, expires_at=self._clock() + ttl_ms / 1000)
        try:
            await self._set(own, entry)
        finally:
            # An eviction can land while an async store's set is committing,
            # and the set can commit even when its await is cancelled (the
            # request may already be on the wire) - so the re-check runs on
            # every exit, and the compensating delete is shielded so the
            # pending cancellation cannot abort it and resurrect the evicted
            # entry for its full TTL. (A delete after a set that raised is an
            # idempotent no-op.)
            if self._generation_moved(gen_key, gen_at_capture):
                with anyio.CancelScope(shield=True):
                    await self._delete(own)

    async def evict_method(self, method: str) -> None:
        """Evict the method's cursor-less entry (notification- or
        cursor-expiry-driven)."""
        await self.evict_key(method, "")

    async def evict_key(self, method: str, params_key: str) -> None:
        """Evict one key from both arms."""
        gen_key = (method, params_key)
        # Bump before deleting so an in-flight fetch that captured earlier
        # cannot write the just-evicted entry back. Only registered keys bump
        # (arbitrary notification uris must not grow the map); the store
        # deletes always run - a persistent store may hold warm entries this
        # coordinator never captured.
        if gen_key in self._generations:
            self._generations[gen_key] += 1
        # Shielded: eviction runs in spawned notification tasks that die with
        # the session - a cancellation between the two deletes would leave one
        # arm serving the evicted entry until its TTL.
        with anyio.CancelScope(shield=True):
            await self._delete(CacheKey(method, params_key, self._private_arm))
            await self._delete(CacheKey(method, params_key, self._public_arm))

    async def evict_for_notification(self, notification: ServerNotification) -> None:
        """Map a server notification to the entries it makes stale.

        Wire-path notifications are dispatched from spawned tasks, so eviction
        is eventual relative to in-flight responses: the generation bump
        closes the write-back race, while a read racing the notification may
        briefly serve the pre-eviction entry (accepted, latency-bounded).
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
        # Hints count only on modern sessions: a legacy peer can also put
        # `ttlMs`/`cacheScope` keys on the wire (the 2025 surfaces validate
        # and discard unknown keys, so wire presence still reaches
        # `model_fields_set`) - wire presence is not a peer-era signal.
        modern = self._negotiated_version() in MODERN_PROTOCOL_VERSIONS
        if modern and "ttl_ms" in result.model_fields_set:
            # An explicit `ttlMs: 0` stays 0 (never overridden by the
            # default), and negatives are unconstructible here - the model
            # enforces ge=0 and the parse seam floors negative wire values -
            # so only the cap applies.
            ttl_ms = result.ttl_ms
        else:
            ttl_ms = self._default_ttl_ms
        scope: Literal["public", "private"] = "public" if modern and result.cache_scope == "public" else "private"
        return min(ttl_ms, MAX_TTL_MS), scope

    def _generation_moved(self, gen_key: tuple[str, str], gen_at_capture: int) -> bool:
        # A key FIFO-dropped from the map can no longer be checked; the guard
        # fails open (the accepted co-tenant race class) rather than
        # discarding the fetch.
        return self._generations.get(gen_key, gen_at_capture) != gen_at_capture

    async def _set(self, key: CacheKey, entry: CacheEntry) -> bool:
        try:
            await self._store.set(key, entry)
        except Exception:  # boundary around user store code: nothing cached, the fetch already succeeded
            self._warn_store_failure("set")
            return False
        self._warned_store_ops.discard("set")
        return True

    async def _delete(self, key: CacheKey) -> bool:
        try:
            await self._store.delete(key)
        except Exception:  # boundary around user store code: callers decide whether a failed delete aborts
            self._warn_store_failure("delete")
            return False
        self._warned_store_ops.discard("delete")
        return True

    def _warn_store_failure(self, kind: Literal["get", "set", "delete"]) -> None:
        # One warning per failure burst, tracked per operation kind: armed by
        # the kind's first failure, re-armed only when that same kind succeeds.
        # A dead store warns once, not once per request - and a store where
        # only `set` is broken warns once too, instead of its healthy deletes
        # re-arming the warning every write cycle.
        if kind not in self._warned_store_ops:
            self._warned_store_ops.add(kind)
            logger.warning("Response cache store operation failed; continuing without the cache", exc_info=True)
