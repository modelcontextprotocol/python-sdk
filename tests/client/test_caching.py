"""`mcp.client.caching`: the `CacheConfig` construction guards, the store
contract every `ResponseCacheStore` implementation must satisfy, the default
in-memory store's bounded `resources/read` FIFO, and the `ClientResponseCache`
coordinator (scope arms, era gate, TTL/scope resolution, eviction, store error
discipline).

The store-contract tests are parametrized over `STORE_FACTORIES`; a
third-party store implementation can be run against the same contract by
adding its factory to the list (or copying the parametrization).
"""

import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
import anyio.lowlevel
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    ListPromptsResult,
    ListToolsResult,
    LoggingMessageNotification,
    LoggingMessageNotificationParams,
    PromptListChangedNotification,
    ReadResourceResult,
    ResourceListChangedNotification,
    ResourceUpdatedNotification,
    ResourceUpdatedNotificationParams,
    ServerNotification,
    ToolListChangedNotification,
)

from mcp.client.caching import (
    MAX_TTL_MS,
    CacheConfig,
    CacheEntry,
    CacheKey,
    ClientResponseCache,
    InMemoryResponseCacheStore,
    ResponseCacheStore,
)

pytestmark = pytest.mark.anyio

STORE_FACTORIES: list[Callable[[], ResponseCacheStore]] = [InMemoryResponseCacheStore]

store_contract = pytest.mark.parametrize("make_store", STORE_FACTORIES, ids=["InMemoryResponseCacheStore"])


def _entry(value: Any = "cached") -> CacheEntry:
    """Entries are opaque payloads at the store layer; only the key matters here."""
    return CacheEntry(value=value, scope="private", expires_at=None)


def _read_key(uri: str) -> CacheKey:
    return CacheKey("resources/read", uri)


# --- Store contract ---


@store_contract
async def test_a_set_entry_round_trips_through_get(make_store: Callable[[], ResponseCacheStore]) -> None:
    """SDK-defined contract: `get` returns an entry equal to the one `set`
    stored under the same three-field key."""
    store = make_store()
    key = CacheKey("tools/list", "", "partition-1")
    entry = CacheEntry(value={"tools": []}, scope="public", expires_at=1700000000.0)
    await store.set(key, entry)
    assert await store.get(key) == entry


@store_contract
async def test_get_misses_for_a_key_never_set(make_store: Callable[[], ResponseCacheStore]) -> None:
    """SDK-defined contract: an unknown key is a miss (`None`), not an error."""
    store = make_store()
    assert await store.get(CacheKey("tools/list")) is None


@store_contract
async def test_keys_differing_in_only_one_field_do_not_collide(
    make_store: Callable[[], ResponseCacheStore],
) -> None:
    """Spec-mandated: the cache key spans the method, the result-affecting
    params, and the authorization context - a store collapsing any one field
    would serve a response across method, params, or principal boundaries."""
    store = make_store()
    base = CacheKey("resources/read", "file:///a", "partition-1")
    keys = [
        base,
        CacheKey("resources/list", base.params_key, base.partition),
        CacheKey(base.method, "file:///b", base.partition),
        CacheKey(base.method, base.params_key, "partition-2"),
    ]
    for i, key in enumerate(keys):
        await store.set(key, _entry(i))
    for i, key in enumerate(keys):
        assert await store.get(key) == _entry(i)


@store_contract
async def test_swapped_params_key_and_partition_values_are_distinct_keys(
    make_store: Callable[[], ResponseCacheStore],
) -> None:
    """SDK-defined contract: identical values in different field positions are
    different keys - the fields are positional, not a bag of strings."""
    store = make_store()
    await store.set(CacheKey("m", "a", "b"), _entry("params=a"))
    await store.set(CacheKey("m", "b", "a"), _entry("params=b"))
    assert await store.get(CacheKey("m", "a", "b")) == _entry("params=a")
    assert await store.get(CacheKey("m", "b", "a")) == _entry("params=b")


@store_contract
async def test_keys_with_field_values_that_concatenate_identically_do_not_collide(
    make_store: Callable[[], ResponseCacheStore],
) -> None:
    """SDK-defined contract: keys MUST be compared as the field tuple, so pairs
    whose fields join to the same string under any delimiter (or none) stay
    distinct - flattening would let crafted values collide across boundaries."""
    store = make_store()
    keys = [
        CacheKey("a", "b.c", "p"),
        CacheKey("a.b", "c", "p"),
        CacheKey("m", "x", "y:z"),
        CacheKey("m", "x:y", "z"),
        CacheKey("m", "u/v", ""),
        CacheKey("m/u", "v", ""),
        CacheKey("ab", "", ""),
        CacheKey("a", "b", ""),
        CacheKey("", "ab", ""),
    ]
    for i, key in enumerate(keys):
        await store.set(key, _entry(i))
    for i, key in enumerate(keys):
        assert await store.get(key) == _entry(i)


@store_contract
async def test_set_replaces_the_entry_for_an_existing_key(make_store: Callable[[], ResponseCacheStore]) -> None:
    """SDK-defined contract: a second `set` under the same key overwrites; the
    store holds at most one entry per key."""
    store = make_store()
    key = CacheKey("tools/list")
    await store.set(key, _entry("first"))
    await store.set(key, _entry("second"))
    assert await store.get(key) == _entry("second")


@store_contract
async def test_delete_removes_only_the_given_key(make_store: Callable[[], ResponseCacheStore]) -> None:
    """SDK-defined contract: `delete` is exact - sibling keys survive."""
    store = make_store()
    doomed = CacheKey("tools/list", "", "partition-1")
    survivor = CacheKey("tools/list", "", "partition-2")
    await store.set(doomed, _entry("doomed"))
    await store.set(survivor, _entry("survivor"))
    await store.delete(doomed)
    assert await store.get(doomed) is None
    assert await store.get(survivor) == _entry("survivor")


@store_contract
async def test_delete_is_idempotent(make_store: Callable[[], ResponseCacheStore]) -> None:
    """SDK-defined contract: deleting an absent key is a no-op, not an error -
    the SDK issues unconditional deletes during eviction."""
    store = make_store()
    key = CacheKey("prompts/list")
    await store.delete(key)
    await store.set(key, _entry())
    await store.delete(key)
    await store.delete(key)
    assert await store.get(key) is None


@store_contract
async def test_clear_removes_every_entry_across_methods_and_partitions(
    make_store: Callable[[], ResponseCacheStore],
) -> None:
    """SDK-defined contract: `clear` empties the store wholesale - every
    method, params_key, and partition."""
    store = make_store()
    keys = [
        CacheKey("tools/list", "", "partition-1"),
        CacheKey("prompts/list", "", "partition-2"),
        CacheKey("resources/read", "file:///a", "partition-1"),
    ]
    for key in keys:
        await store.set(key, _entry())
    await store.clear()
    for key in keys:
        assert await store.get(key) is None


# --- CacheConfig guards ---


def test_cache_config_defaults_construct_an_unshared_zero_ttl_config() -> None:
    """SDK-defined defaults: in-memory store minted per client, empty
    partition, no identity override, hint-less results uncached, wall clock,
    and public-entry sharing OFF (sharing is an explicit operator opt-in)."""
    config = CacheConfig()
    assert config.store is None
    assert config.partition == ""
    assert config.target_id is None
    assert config.default_ttl_ms == 0
    assert config.clock is time.time
    assert config.share_public is False


def test_a_custom_store_without_a_partition_is_rejected_at_construction() -> None:
    """SDK-defined guard: a custom store is shareable, so omitting the
    authorization-context partition would let private entries cross
    principals - rejected at `CacheConfig` construction, not on first use."""
    with pytest.raises(ValueError) as exc:
        CacheConfig(store=InMemoryResponseCacheStore())
    assert str(exc.value) == snapshot("a custom store requires an explicit partition")


def test_a_custom_store_with_an_explicit_partition_constructs() -> None:
    """SDK-defined: the partition guard is satisfied by any non-empty
    operator-supplied principal id."""
    store = InMemoryResponseCacheStore()
    config = CacheConfig(store=store, partition="token-subject-1")
    assert config.store is store
    assert config.partition == "token-subject-1"


def test_an_empty_target_id_is_rejected_at_construction() -> None:
    """SDK-defined guard: an explicit empty `target_id` would hash to the one
    shared `sha256("")` identity, collapsing distinct servers onto it -
    rejected at construction; omit the field (None) to derive an identity."""
    with pytest.raises(ValueError) as exc:
        CacheConfig(target_id="")
    assert str(exc.value) == snapshot("target_id must be a non-empty string or omitted")


def test_a_negative_default_ttl_is_rejected_at_construction() -> None:
    """SDK-defined guard: a negative configured TTL is a programming error,
    rejected at construction (negative `ttlMs` from the wire is tolerated as 0
    at the parse seam instead)."""
    with pytest.raises(ValueError) as exc:
        CacheConfig(default_ttl_ms=-1)
    assert str(exc.value) == snapshot("default_ttl_ms must be >= 0, got -1")


# --- InMemoryResponseCacheStore read cap ---


async def test_a_new_read_key_at_the_cap_evicts_the_oldest_read_key() -> None:
    """SDK-defined bound: `resources/read` keys are unbounded in principle (one
    per uri), so storing a new one at the cap drops the oldest, FIFO."""
    store = InMemoryResponseCacheStore(max_read_entries=2)
    await store.set(_read_key("file:///a"), _entry("a"))
    await store.set(_read_key("file:///b"), _entry("b"))
    await store.set(_read_key("file:///c"), _entry("c"))
    assert await store.get(_read_key("file:///a")) is None
    assert await store.get(_read_key("file:///b")) == _entry("b")
    assert await store.get(_read_key("file:///c")) == _entry("c")


async def test_replacing_a_read_key_at_the_cap_neither_evicts_nor_refreshes_its_age() -> None:
    """SDK-defined: replacement is not growth (no double-count, nothing
    evicted) and does not renew the key's position - eviction order is
    first-insertion order (FIFO), not recency (LRU)."""
    store = InMemoryResponseCacheStore(max_read_entries=2)
    await store.set(_read_key("file:///a"), _entry("a"))
    await store.set(_read_key("file:///b"), _entry("b"))
    await store.set(_read_key("file:///a"), _entry("a-replaced"))
    assert await store.get(_read_key("file:///a")) == _entry("a-replaced")
    assert await store.get(_read_key("file:///b")) == _entry("b")
    await store.set(_read_key("file:///c"), _entry("c"))
    assert await store.get(_read_key("file:///a")) is None
    assert await store.get(_read_key("file:///b")) == _entry("b")


async def test_only_read_keys_count_toward_the_cap_and_only_read_keys_are_evicted() -> None:
    """SDK-defined: the non-read cacheable methods are a small closed key set -
    they neither consume cap slots nor ever get cap-evicted."""
    store = InMemoryResponseCacheStore(max_read_entries=1)
    list_keys = [
        CacheKey("tools/list"),
        CacheKey("prompts/list"),
        CacheKey("resources/list"),
        CacheKey("resources/templates/list"),
        CacheKey("server/discover"),
    ]
    for key in list_keys:
        await store.set(key, _entry(key.method))
    await store.set(_read_key("file:///a"), _entry("a"))
    for key in list_keys:
        assert await store.get(key) == _entry(key.method)
    await store.set(_read_key("file:///b"), _entry("b"))
    assert await store.get(_read_key("file:///a")) is None
    assert await store.get(_read_key("file:///b")) == _entry("b")
    for key in list_keys:
        assert await store.get(key) == _entry(key.method)


async def test_a_non_read_set_never_triggers_eviction_even_with_reads_at_the_cap() -> None:
    """SDK-defined: only storing a NEW read key can evict - a non-read `set`
    while reads sit at the cap leaves them untouched."""
    store = InMemoryResponseCacheStore(max_read_entries=1)
    await store.set(_read_key("file:///a"), _entry("a"))
    await store.set(CacheKey("tools/list"), _entry("tools"))
    assert await store.get(_read_key("file:///a")) == _entry("a")
    assert await store.get(CacheKey("tools/list")) == _entry("tools")


async def test_a_zero_cap_disables_read_eviction() -> None:
    """SDK-defined: `max_read_entries=0` means unbounded read entries."""
    store = InMemoryResponseCacheStore(max_read_entries=0)
    uris = [f"file:///{i}" for i in range(5)]
    for uri in uris:
        await store.set(_read_key(uri), _entry(uri))
    for uri in uris:
        assert await store.get(_read_key(uri)) == _entry(uri)


async def test_deleting_a_read_key_frees_its_cap_slot() -> None:
    """SDK-defined: the cap counts live entries, so a deleted read key's slot
    is reusable without evicting anything."""
    store = InMemoryResponseCacheStore(max_read_entries=1)
    await store.set(_read_key("file:///a"), _entry("a"))
    await store.delete(_read_key("file:///a"))
    await store.set(_read_key("file:///b"), _entry("b"))
    assert await store.get(_read_key("file:///b")) == _entry("b")


def test_a_negative_read_cap_is_rejected_at_construction() -> None:
    """SDK-defined guard: a negative cap is meaningless (0 already means
    uncapped) and would otherwise evict on every read insert."""
    with pytest.raises(ValueError) as exc:
        InMemoryResponseCacheStore(max_read_entries=-1)
    assert str(exc.value) == snapshot("max_read_entries must be >= 0, got -1")


# --- ClientResponseCache coordinator ---

MODERN_VERSION = "2026-07-28"
LEGACY_VERSION = "2025-11-25"


class _ManualClock:
    """Injected wall clock: tests advance `now` instead of sleeping."""

    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def _coordinator(
    store: ResponseCacheStore,
    *,
    partition: str = "",
    arm_id: str = "arm",
    default_ttl_ms: int = 0,
    clock: _ManualClock | None = None,
    share_public: bool = False,
    version: str | None = MODERN_VERSION,
    generation_map_cap: int = 4096,
) -> ClientResponseCache:
    return ClientResponseCache(
        store=store,
        partition=partition,
        arm_id=arm_id,
        default_ttl_ms=default_ttl_ms,
        clock=clock or _ManualClock(),
        share_public=share_public,
        negotiated_version=lambda: version,
        generation_map_cap=generation_map_cap,
    )


def _private_arm(arm_id: str = "arm", partition: str = "") -> str:
    return json.dumps(["private", arm_id, partition])


def _public_arm(arm_id: str = "arm", partition: str = "") -> str:
    return json.dumps(["public", arm_id, partition])


def _wire_result(ttl_ms: int | None = None, cache_scope: str | None = None) -> ListToolsResult:
    """A `tools/list` result as parsed off the wire; `None` omits the hint so
    it stays out of `model_fields_set`."""
    payload: dict[str, Any] = {"tools": []}
    if ttl_ms is not None:
        payload["ttlMs"] = ttl_ms
    if cache_scope is not None:
        payload["cacheScope"] = cache_scope
    return ListToolsResult.model_validate(payload)


def _read_result(ttl_ms: int) -> ReadResourceResult:
    return ReadResourceResult.model_validate({"contents": [], "ttlMs": ttl_ms})


class _ScriptedStore:
    """In-memory store that logs `(op, key)` and can await one-shot hooks
    around an operation's commit, modelling an async store mid-commit when an
    eviction or a cancellation lands."""

    def __init__(self) -> None:
        self.inner = InMemoryResponseCacheStore()
        self.ops: list[tuple[str, CacheKey]] = []
        self.before_set_commits: Callable[[], Awaitable[None]] | None = None
        self.after_set_commits: Callable[[], Awaitable[None]] | None = None
        self.after_delete_commits: Callable[[], Awaitable[None]] | None = None

    async def get(self, key: CacheKey) -> CacheEntry | None:
        self.ops.append(("get", key))
        return await self.inner.get(key)

    async def set(self, key: CacheKey, entry: CacheEntry) -> None:
        self.ops.append(("set", key))
        if self.before_set_commits is not None:
            hook, self.before_set_commits = self.before_set_commits, None
            await hook()
        await self.inner.set(key, entry)
        if self.after_set_commits is not None:
            hook, self.after_set_commits = self.after_set_commits, None
            await hook()

    async def delete(self, key: CacheKey) -> None:
        self.ops.append(("delete", key))
        await self.inner.delete(key)
        if self.after_delete_commits is not None:
            hook, self.after_delete_commits = self.after_delete_commits, None
            await hook()

    async def clear(self) -> None:
        raise NotImplementedError


class _FailingStore:
    """In-memory store whose operations raise while their flag is set; the
    flags toggle so tests can model recovery."""

    def __init__(self, *, fail_get: bool = False, fail_set: bool = False, fail_delete: bool = False) -> None:
        self.inner = InMemoryResponseCacheStore()
        self.fail_get = fail_get
        self.fail_set = fail_set
        self.fail_delete = fail_delete

    async def get(self, key: CacheKey) -> CacheEntry | None:
        if self.fail_get:
            raise RuntimeError("store get failed")
        return await self.inner.get(key)

    async def set(self, key: CacheKey, entry: CacheEntry) -> None:
        if self.fail_set:
            raise RuntimeError("store set failed")
        await self.inner.set(key, entry)

    async def delete(self, key: CacheKey) -> None:
        if self.fail_delete:
            raise RuntimeError("store delete failed")
        await self.inner.delete(key)

    async def clear(self) -> None:
        raise NotImplementedError


class _ArmDeleteFailingStore:
    """In-memory store whose `delete` raises only for keys on the given arm,
    modelling a write whose opposite-arm cleanup fails while everything else
    works. A write hitting that failure never reaches `set`."""

    def __init__(self, failing_arm: str) -> None:
        self.inner = InMemoryResponseCacheStore()
        self.failing_arm = failing_arm

    async def get(self, key: CacheKey) -> CacheEntry | None:
        return await self.inner.get(key)

    async def set(self, key: CacheKey, entry: CacheEntry) -> None:
        raise NotImplementedError

    async def delete(self, key: CacheKey) -> None:
        if key.partition == self.failing_arm:
            raise RuntimeError("store delete failed")
        await self.inner.delete(key)

    async def clear(self) -> None:
        raise NotImplementedError


class _RehydratingStore:
    """Models a persistent store whose `get` returns what its deserializer
    produced - possibly not the shape `set` received."""

    def __init__(self, rehydrated: Any) -> None:
        self.rehydrated = rehydrated

    async def get(self, key: CacheKey) -> CacheEntry | None:
        return self.rehydrated

    async def set(self, key: CacheKey, entry: CacheEntry) -> None:
        raise NotImplementedError

    async def delete(self, key: CacheKey) -> None:
        raise NotImplementedError

    async def clear(self) -> None:
        raise NotImplementedError


# --- Coordinator: era gate ---


@pytest.mark.parametrize("version", [LEGACY_VERSION, None], ids=["legacy", "pre-negotiation"])
async def test_hints_from_a_non_modern_session_are_ignored(version: str | None) -> None:
    """SDK-defined era gate: `ttlMs`/`cacheScope` are 2026-07-28 assertions. A
    legacy peer can inject the keys onto the wire (the 2025 surfaces validate
    and discard unknown keys, so they reach `model_fields_set`), so wire
    presence is not trusted: on a non-modern session every result is
    hint-absent - with the default `default_ttl_ms=0`, nothing is stored."""
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store, version=version)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000, cache_scope="public"), gen, "use")
    assert await cache.read("tools/list", "") is None
    assert await store.get(CacheKey("tools/list", "", _private_arm())) is None
    assert await store.get(CacheKey("tools/list", "", _public_arm())) is None


async def test_a_legacy_session_with_a_default_ttl_caches_on_the_private_arm_only() -> None:
    """SDK-defined era gate: the operator's `default_ttl_ms` still applies on
    legacy sessions, but an injected `cacheScope: "public"` cannot promote the
    entry, and an injected `ttlMs` does not shorten (or extend) its life."""
    store = InMemoryResponseCacheStore()
    clock = _ManualClock()
    cache = _coordinator(store, version=LEGACY_VERSION, default_ttl_ms=60_000, clock=clock)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=5, cache_scope="public"), gen, "use")
    private_entry = await store.get(CacheKey("tools/list", "", _private_arm()))
    assert private_entry is not None
    assert private_entry.scope == "private"
    assert await store.get(CacheKey("tools/list", "", _public_arm())) is None
    clock.now += 1.0  # well past the injected 5ms; the default 60s governs
    assert await cache.read("tools/list", "") == _wire_result(ttl_ms=5, cache_scope="public")


# --- Coordinator: TTL and scope resolution ---


async def test_an_explicit_zero_ttl_is_not_overridden_by_the_default_ttl() -> None:
    """Spec-mandated: `ttlMs: 0` means immediately stale. The configured
    `default_ttl_ms` fills in only for hint-ABSENT results - an explicit 0
    stores nothing."""
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store, default_ttl_ms=60_000)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=0), gen, "use")
    assert await store.get(CacheKey("tools/list", "", _private_arm())) is None
    assert await store.get(CacheKey("tools/list", "", _public_arm())) is None


async def test_a_hint_absent_modern_result_uses_the_default_ttl_privately() -> None:
    """SDK-defined: on a modern session a result without `ttlMs` in
    `model_fields_set` gets `default_ttl_ms` and scope `"private"`, expiring
    exactly when the default says."""
    store = InMemoryResponseCacheStore()
    clock = _ManualClock()
    cache = _coordinator(store, default_ttl_ms=60_000, clock=clock)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(), gen, "use")
    entry = await store.get(CacheKey("tools/list", "", _private_arm()))
    assert entry is not None
    assert entry.scope == "private"
    assert entry.expires_at == clock.now + 60.0
    assert await cache.read("tools/list", "") == _wire_result()
    clock.now += 60.0
    assert await cache.read("tools/list", "") is None


async def test_a_ttl_above_24_hours_is_clamped_to_the_cap() -> None:
    """SDK-defined hardening (SEP-2549 security discussion): a server cannot
    pin an entry beyond 24 hours - the stored expiry is clamped to
    `MAX_TTL_MS`."""
    store = InMemoryResponseCacheStore()
    clock = _ManualClock()
    cache = _coordinator(store, clock=clock)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=7 * MAX_TTL_MS), gen, "use")
    entry = await store.get(CacheKey("tools/list", "", _private_arm()))
    assert entry is not None
    assert entry.expires_at == clock.now + MAX_TTL_MS / 1000


async def test_a_public_result_lands_on_the_public_arm_and_clears_the_private_arm() -> None:
    """Spec-mandated scope routing plus the SDK's no-stale-pair invariant:
    when a key's scope flips, writing the new arm deletes the other so the two
    arms never both answer."""
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen, "use")
    assert await store.get(CacheKey("tools/list", "", _private_arm())) is not None
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000, cache_scope="public"), gen, "use")
    public_entry = await store.get(CacheKey("tools/list", "", _public_arm()))
    assert public_entry is not None
    assert public_entry.scope == "public"
    assert await store.get(CacheKey("tools/list", "", _private_arm())) is None


# --- Coordinator: partition arms and the scope guard ---


async def test_arm_key_layout_is_pinned_for_shared_store_compatibility() -> None:
    """SDK-defined persistence contract: arm strings are the cross-process
    store key material, so their layout is pinned - JSON arrays of the scope,
    the hashed server identity, and (unless `share_public`) the partition."""
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store, partition="tenant-a", arm_id="abc123", default_ttl_ms=60_000)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(), gen, "use")
    assert await store.get(CacheKey("tools/list", "", snapshot('["private", "abc123", "tenant-a"]'))) is not None
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000, cache_scope="public"), gen, "use")
    assert await store.get(CacheKey("tools/list", "", snapshot('["public", "abc123", "tenant-a"]'))) is not None
    shared = _coordinator(store, partition="tenant-a", arm_id="abc123", share_public=True)
    gen = shared.capture("tools/list", "")
    await shared.write("tools/list", "", _wire_result(ttl_ms=60_000, cache_scope="public"), gen, "use")
    assert await store.get(CacheKey("tools/list", "", snapshot('["public", "abc123"]'))) is not None


async def test_public_entries_do_not_cross_partitions_by_default() -> None:
    """SDK security default (deviates from the ts SDK): the public arm is
    partition-scoped, so a server stamping `cacheScope: "public"` on
    per-tenant data (bug or malice) cannot leak one tenant's response to
    another through a shared store."""
    store = InMemoryResponseCacheStore()
    tenant_a = _coordinator(store, partition="tenant-a")
    tenant_b = _coordinator(store, partition="tenant-b")
    gen = tenant_a.capture("tools/list", "")
    await tenant_a.write("tools/list", "", _wire_result(ttl_ms=60_000, cache_scope="public"), gen, "use")
    assert await tenant_a.read("tools/list", "") == _wire_result(ttl_ms=60_000, cache_scope="public")
    assert await tenant_b.read("tools/list", "") is None


async def test_share_public_serves_public_entries_across_partitions_but_never_private_ones() -> None:
    """SDK-defined opt-in: `share_public=True` drops the partition from the
    public arm, sharing server-asserted-public entries fleet-wide. Private
    entries still never cross partitions."""
    store = InMemoryResponseCacheStore()
    tenant_a = _coordinator(store, partition="tenant-a", share_public=True)
    tenant_b = _coordinator(store, partition="tenant-b", share_public=True)
    gen = tenant_a.capture("tools/list", "")
    await tenant_a.write("tools/list", "", _wire_result(ttl_ms=60_000, cache_scope="public"), gen, "use")
    assert await tenant_b.read("tools/list", "") == _wire_result(ttl_ms=60_000, cache_scope="public")
    private_result = ListPromptsResult.model_validate({"prompts": [], "ttlMs": 60_000})
    gen = tenant_a.capture("prompts/list", "")
    await tenant_a.write("prompts/list", "", private_result, gen, "use")
    assert await tenant_b.read("prompts/list", "") is None


async def test_a_private_scoped_entry_under_the_public_arm_is_not_served() -> None:
    """SDK defense in depth: the arm routes, the entry's scope verifies - a
    `"private"` entry sitting under the shared arm (a corrupted or pre-seeded
    store) is refused, not served across the boundary."""
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store)
    await store.set(
        CacheKey("tools/list", "", _public_arm()),
        CacheEntry(value=_wire_result(), scope="private", expires_at=2_000_000.0),
    )
    assert await cache.read("tools/list", "") is None


async def test_a_stale_private_entry_does_not_shadow_a_fresh_public_one() -> None:
    """SDK-defined fall-through: a stale private-arm entry is a miss for
    arm-probing purposes, so after a server scope flip (private -> public,
    with the public entry seeded by another client sharing the store) the
    fresh public entry is served, not shadowed into a spurious miss."""
    store = InMemoryResponseCacheStore()
    clock = _ManualClock()
    cache = _coordinator(store, clock=clock)
    await store.set(
        CacheKey("tools/list", "", _private_arm()),
        CacheEntry(value=_wire_result(), scope="private", expires_at=clock.now - 1.0),
    )
    public_result = _wire_result(ttl_ms=60_000, cache_scope="public")
    await store.set(
        CacheKey("tools/list", "", _public_arm()),
        CacheEntry(value=public_result, scope="public", expires_at=clock.now + 60.0),
    )
    assert await cache.read("tools/list", "") == public_result


async def test_an_entry_without_an_expiry_is_never_fresh() -> None:
    """SDK-defined: `expires_at=None` means never fresh - a store rehydrating
    entries without expiry metadata yields misses, not immortal entries."""
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store)
    await store.set(
        CacheKey("tools/list", "", _private_arm()),
        CacheEntry(value=_wire_result(), scope="private", expires_at=None),
    )
    assert await cache.read("tools/list", "") is None


# --- Coordinator: write ordering ---


async def test_write_deletes_the_opposite_arm_before_setting_its_own() -> None:
    """SDK-defined ordering: the opposite arm is deleted before the own-arm
    set, so a cancellation between the two operations leaves a miss - never
    two arms answering for one key."""
    store = _ScriptedStore()
    cache = _coordinator(store)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000, cache_scope="public"), gen, "use")
    assert store.ops == [
        ("delete", CacheKey("tools/list", "", _private_arm())),
        ("set", CacheKey("tools/list", "", _public_arm())),
    ]


async def test_an_eviction_landing_during_an_async_set_is_compensated() -> None:
    """SDK-defined TOCTOU re-check. Steps: (1) write captures, deletes the
    opposite arm, and issues `set`; (2) before the store commits, an eviction
    runs fully (bump + deletes, which see nothing); (3) the set commits the
    now-stale entry; (4) the post-set generation re-check fires a compensating
    delete, so the evicted key does not resurface."""
    store = _ScriptedStore()
    cache = _coordinator(store)
    gen = cache.capture("tools/list", "")

    async def evict_mid_commit() -> None:
        await cache.evict_method("tools/list")

    store.before_set_commits = evict_mid_commit
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen, "use")
    private_key = CacheKey("tools/list", "", _private_arm())
    public_key = CacheKey("tools/list", "", _public_arm())
    assert store.ops == [
        ("delete", public_key),  # write: opposite arm first
        ("set", private_key),  # write: own arm, commit still pending
        ("delete", private_key),  # eviction (sees nothing - not committed yet)
        ("delete", public_key),  # eviction
        ("delete", private_key),  # post-set re-check compensation
    ]
    assert await store.inner.get(private_key) is None
    assert await cache.read("tools/list", "") is None


async def test_a_cancellation_landing_as_the_set_commits_still_compensates_an_eviction() -> None:
    """SDK-defined: the eviction re-check survives cancellation. Steps: (1)
    write deletes the opposite arm and issues `set`; (2) before the store
    commits, an eviction runs fully (its deletes see nothing) and the caller's
    scope is cancelled; (3) the set commits and the cancellation is delivered
    at the store's next checkpoint - a timeout firing while an async store's
    set is already on the wire; (4) the shielded compensating delete still
    runs, so the evicted entry is not resurrected for its full TTL."""
    store = _ScriptedStore()
    cache = _coordinator(store)
    gen = cache.capture("tools/list", "")
    private_key = CacheKey("tools/list", "", _private_arm())
    public_key = CacheKey("tools/list", "", _public_arm())
    with anyio.CancelScope() as scope:

        async def evict_then_cancel() -> None:
            await cache.evict_method("tools/list")
            scope.cancel()

        store.before_set_commits = evict_then_cancel
        store.after_set_commits = anyio.lowlevel.checkpoint  # first checkpoint after the commit
        await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen, "use")
    assert scope.cancelled_caught
    assert store.ops == [
        ("delete", public_key),  # write: opposite arm first
        ("set", private_key),  # write: own arm, commit still pending
        ("delete", private_key),  # eviction (sees nothing - not committed yet)
        ("delete", public_key),  # eviction
        ("delete", private_key),  # post-set re-check compensation, shielded
    ]
    assert await store.inner.get(private_key) is None


async def test_a_cancellation_during_the_refresh_purge_still_purges_both_arms() -> None:
    """SDK-defined: the `mode="refresh"` purge is shielded - a cancellation
    delivered between its two arm deletes must not leave the warm
    opposite-arm entry that the refetch superseded."""
    store = _ScriptedStore()
    cache = _coordinator(store)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000, cache_scope="public"), gen, "use")
    public_key = CacheKey("tools/list", "", _public_arm())
    assert await store.inner.get(public_key) is not None
    with anyio.CancelScope() as scope:
        scope.cancel()
        # The cancellation would be delivered at the first checkpoint after the
        # first (private-arm) delete commits, skipping the warm public arm.
        store.after_delete_commits = anyio.lowlevel.checkpoint
        await cache.write("tools/list", "", _wire_result(ttl_ms=0), gen, "refresh")
    assert await store.inner.get(public_key) is None


async def test_a_cancellation_during_an_eviction_still_evicts_both_arms() -> None:
    """SDK-defined: eviction's two arm deletes are shielded - a notification
    task cancelled mid-eviction (e.g. session teardown) must not leave one arm
    serving the evicted entry until its TTL."""
    store = _ScriptedStore()
    cache = _coordinator(store)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000, cache_scope="public"), gen, "use")
    public_key = CacheKey("tools/list", "", _public_arm())
    with anyio.CancelScope() as scope:
        scope.cancel()
        # The cancellation would be delivered at the first checkpoint after the
        # first (private-arm) delete commits, skipping the warm public arm.
        store.after_delete_commits = anyio.lowlevel.checkpoint
        await cache.evict_method("tools/list")
    assert await store.inner.get(public_key) is None


# --- Coordinator: store error discipline ---


async def test_a_raising_store_get_is_a_cache_miss() -> None:
    """SDK error discipline: a raising store never fails the caller - a
    read-path `get` raise is a miss."""
    store = _FailingStore(fail_get=True)
    cache = _coordinator(store)
    assert await cache.read("tools/list", "") is None


@pytest.mark.parametrize(
    "rehydrated",
    [
        CacheEntry(value={"tools": []}, scope="private", expires_at=2_000_000.0),
        {"value": {"tools": []}, "scope": "private", "expires_at": 2_000_000.0},
    ],
    ids=["dict-value", "dict-entry"],
)
async def test_an_entry_rehydrated_into_the_wrong_shape_is_a_warned_miss(
    rehydrated: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """SDK error discipline: a persistent store has no method-to-model mapping
    to rehydrate with, so its `get` may return serialized shapes (a dict where
    the result model was stored, or a dict for the whole entry); the read
    degrades to a warned miss instead of failing the call - and a store that
    is persistently misconfigured this way is one warning burst, not one
    warning per cached read."""
    cache = _coordinator(_RehydratingStore(rehydrated))
    with caplog.at_level(logging.WARNING, logger="mcp.client.caching"):
        assert await cache.read("tools/list", "") is None
        assert await cache.read("tools/list", "") is None
    assert len(caplog.records) == 1


async def test_a_raising_opposite_arm_delete_aborts_the_write() -> None:
    """SDK error discipline: if the opposite-arm delete fails, setting anyway
    could leave both arms populated - the write aborts with nothing cached."""
    store = _FailingStore(fail_delete=True)
    cache = _coordinator(store)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen, "use")
    assert await store.inner.get(CacheKey("tools/list", "", _private_arm())) is None
    assert await store.inner.get(CacheKey("tools/list", "", _public_arm())) is None


async def test_a_failed_opposite_arm_delete_degrades_the_key_to_a_full_miss() -> None:
    """SDK error discipline: when only the opposite-arm delete fails, the write
    cannot set its own arm (two arms might answer) - but the warm own-arm
    entry was superseded by the fetch, so it is best-effort deleted too: both
    arms read as misses, and the write itself never raises."""
    store = _ArmDeleteFailingStore(failing_arm=_public_arm())
    cache = _coordinator(store)
    await store.inner.set(
        CacheKey("tools/list", "", _private_arm()),
        CacheEntry(value=_wire_result(), scope="private", expires_at=2_000_000.0),
    )
    assert await cache.read("tools/list", "") is not None  # the warm own-arm entry
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen, "use")
    assert await store.inner.get(CacheKey("tools/list", "", _private_arm())) is None
    assert await store.inner.get(CacheKey("tools/list", "", _public_arm())) is None
    assert await cache.read("tools/list", "") is None


async def test_a_raising_store_set_caches_nothing_and_does_not_raise() -> None:
    """SDK error discipline: a `set` raise is logged and swallowed - the fetch
    already succeeded, the result just is not cached."""
    store = _FailingStore(fail_set=True)
    cache = _coordinator(store)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen, "use")
    assert await cache.read("tools/list", "") is None


async def test_eviction_with_a_raising_delete_still_bumps_the_generation() -> None:
    """SDK error discipline (bump-first): even when the store deletes raise,
    the eviction's generation bump lands - an in-flight fetch captured before
    the eviction cannot write back, while a fetch captured after it can."""
    store = _FailingStore()
    cache = _coordinator(store)
    stale_gen = cache.capture("tools/list", "")  # fetch in flight when the eviction lands
    store.fail_delete = True
    await cache.evict_method("tools/list")  # deletes raise; the bump already happened
    store.fail_delete = False
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), stale_gen, "use")
    assert await store.inner.get(CacheKey("tools/list", "", _private_arm())) is None
    fresh_gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), fresh_gen, "use")
    assert await cache.read("tools/list", "") == _wire_result(ttl_ms=60_000)


async def test_store_failures_warn_once_per_burst(caplog: pytest.LogCaptureFixture) -> None:
    """SDK-defined logging: consecutive store failures log a single warning; a
    successful operation re-arms it so the next burst warns again."""
    store = _FailingStore(fail_get=True)
    cache = _coordinator(store)
    with caplog.at_level(logging.WARNING, logger="mcp.client.caching"):
        await cache.read("tools/list", "")  # consecutive failing reads, one burst
        await cache.read("tools/list", "")
        assert len(caplog.records) == 1
        store.fail_get = False
        await cache.read("tools/list", "")  # success re-arms the warning
        store.fail_get = True
        await cache.read("tools/list", "")
        assert len(caplog.records) == 2
    assert caplog.messages[0] == snapshot("Response cache store operation failed; continuing without the cache")


async def test_a_set_only_store_failure_warns_once_across_write_cycles(caplog: pytest.LogCaptureFixture) -> None:
    """SDK-defined logging: the warning burst is tracked per operation kind -
    a store where only `set` is broken warns once across write cycles, the
    healthy deletes in between never re-arming it; only a `set` succeeding
    re-arms the `set` warning."""
    store = _FailingStore(fail_set=True)
    cache = _coordinator(store)
    with caplog.at_level(logging.WARNING, logger="mcp.client.caching"):
        for _ in range(3):  # each cycle: opposite-arm delete succeeds, then the set fails
            gen = cache.capture("tools/list", "")
            await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen, "use")
        assert len(caplog.records) == 1
        store.fail_set = False
        gen = cache.capture("tools/list", "")
        await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen, "use")  # set succeeds, re-arms
        store.fail_set = True
        gen = cache.capture("tools/list", "")
        await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen, "use")
    assert len(caplog.records) == 2


# --- Coordinator: generation discipline ---


async def test_an_eviction_between_capture_and_write_discards_the_write() -> None:
    """Spec-aligned race rule: a fetch in flight when its key is evicted must
    not write the evicted entry back - the generation captured before the send
    no longer matches at write time."""
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store)
    gen = cache.capture("tools/list", "")
    await cache.evict_method("tools/list")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen, "use")
    assert await store.get(CacheKey("tools/list", "", _private_arm())) is None
    assert await store.get(CacheKey("tools/list", "", _public_arm())) is None


async def test_recapturing_a_registered_key_returns_its_current_generation() -> None:
    """SDK-defined: `capture` re-reads, it does not reset - after an eviction
    a new fetch captures the bumped generation and its write lands."""
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store)
    gen_before = cache.capture("tools/list", "")
    await cache.evict_method("tools/list")
    gen_after = cache.capture("tools/list", "")
    assert gen_after != gen_before
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen_after, "use")
    assert await cache.read("tools/list", "") == _wire_result(ttl_ms=60_000)


async def test_the_generation_map_drops_the_oldest_key_at_its_cap() -> None:
    """SDK-defined bound (cap parametrized small; 4096 in production):
    registering a new key at the cap drops the oldest, whose race guard
    degrades to the accepted co-tenant class - an eviction racing the dropped
    key's in-flight fetch goes undetected and its write lands, while a
    still-registered key's write is discarded."""
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store, generation_map_cap=2)
    gen_a = cache.capture("resources/read", "file:///a")
    gen_b = cache.capture("resources/read", "file:///b")
    cache.capture("resources/read", "file:///c")  # at the cap: drops file:///a
    await cache.evict_key("resources/read", "file:///a")  # unregistered: no bump
    await cache.evict_key("resources/read", "file:///b")  # registered: bump
    await cache.write("resources/read", "file:///a", _read_result(ttl_ms=60_000), gen_a, "use")
    await cache.write("resources/read", "file:///b", _read_result(ttl_ms=60_000), gen_b, "use")
    assert await cache.read("resources/read", "file:///a") is not None  # degraded guard fails open
    assert await cache.read("resources/read", "file:///b") is None  # guard held


# --- Coordinator: eviction ---


async def test_a_refresh_resolving_uncacheable_purges_the_warm_entry() -> None:
    """SDK-defined: a `cache_mode="refresh"` whose fresh result resolves to an
    uncacheable TTL deletes both arms - the refetch superseded the warm entry,
    which must not be served again."""
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen, "use")
    assert await cache.read("tools/list", "") is not None
    await cache.write("tools/list", "", _wire_result(ttl_ms=0), gen, "refresh")
    assert await store.get(CacheKey("tools/list", "", _private_arm())) is None
    assert await store.get(CacheKey("tools/list", "", _public_arm())) is None


async def test_evict_key_on_an_unregistered_key_still_deletes_both_arms() -> None:
    """SDK-defined: a persistent store may hold warm entries from a prior
    process that this coordinator never captured - eviction always issues the
    store deletes, registered or not."""
    store = InMemoryResponseCacheStore()
    await store.set(
        CacheKey("resources/read", "file:///warm", _private_arm()),
        CacheEntry(value=_read_result(ttl_ms=60_000), scope="private", expires_at=2_000_000.0),
    )
    await store.set(
        CacheKey("resources/read", "file:///warm", _public_arm()),
        CacheEntry(value=_read_result(ttl_ms=60_000), scope="public", expires_at=2_000_000.0),
    )
    cache = _coordinator(store)
    await cache.evict_key("resources/read", "file:///warm")
    assert await store.get(CacheKey("resources/read", "file:///warm", _private_arm())) is None
    assert await store.get(CacheKey("resources/read", "file:///warm", _public_arm())) is None


@pytest.mark.parametrize(
    ("notification", "evicted"),
    [
        (ToolListChangedNotification(), {("tools/list", "")}),
        (PromptListChangedNotification(), {("prompts/list", "")}),
        (ResourceListChangedNotification(), {("resources/list", ""), ("resources/templates/list", "")}),
        (
            ResourceUpdatedNotification(params=ResourceUpdatedNotificationParams(uri="file:///a")),
            {("resources/read", "file:///a")},
        ),
        (
            LoggingMessageNotification(params=LoggingMessageNotificationParams(level="info", data="x")),
            set[tuple[str, str]](),
        ),
    ],
    ids=["tools-list-changed", "prompts-list-changed", "resources-list-changed", "resource-updated", "unrelated"],
)
async def test_notifications_evict_exactly_their_mapped_entries(
    notification: ServerNotification, evicted: set[tuple[str, str]]
) -> None:
    """Spec SHOULD (notifications invalidate) plus negative space: each
    list_changed notification evicts its own method's entry and nothing else,
    resources/list_changed co-evicts the templates list, resources/updated
    evicts only the named uri, and an unrelated notification evicts nothing."""
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store)
    seeded = [
        ("tools/list", ""),
        ("prompts/list", ""),
        ("resources/list", ""),
        ("resources/templates/list", ""),
        ("resources/read", "file:///a"),
        ("resources/read", "file:///b"),
    ]
    for method, params_key in seeded:
        # The value's content is irrelevant to eviction; any cacheable model serves.
        await store.set(
            CacheKey(method, params_key, _private_arm()),
            CacheEntry(value=_wire_result(), scope="private", expires_at=2_000_000.0),
        )
    await cache.evict_for_notification(notification)
    for method, params_key in seeded:
        if (method, params_key) in evicted:
            assert await cache.read(method, params_key) is None
        else:
            assert await cache.read(method, params_key) is not None
