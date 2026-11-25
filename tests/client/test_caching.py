"""Tests for `mcp.client.caching`. The store-contract tests are parametrized
over `STORE_FACTORIES`; a third-party store can be run against the same
contract by adding its factory."""

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
    store = make_store()
    key = CacheKey("tools/list", "", "partition-1")
    entry = CacheEntry(value={"tools": []}, scope="public", expires_at=1700000000.0)
    await store.set(key, entry)
    assert await store.get(key) == entry


@store_contract
async def test_get_misses_for_a_key_never_set(make_store: Callable[[], ResponseCacheStore]) -> None:
    store = make_store()
    assert await store.get(CacheKey("tools/list")) is None


@store_contract
async def test_keys_differing_in_only_one_field_do_not_collide(
    make_store: Callable[[], ResponseCacheStore],
) -> None:
    """Spec-mandated: collapsing any key field would serve responses across method, params, or principal boundaries."""
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
    store = make_store()
    await store.set(CacheKey("m", "a", "b"), _entry("params=a"))
    await store.set(CacheKey("m", "b", "a"), _entry("params=b"))
    assert await store.get(CacheKey("m", "a", "b")) == _entry("params=a")
    assert await store.get(CacheKey("m", "b", "a")) == _entry("params=b")


@store_contract
async def test_keys_with_field_values_that_concatenate_identically_do_not_collide(
    make_store: Callable[[], ResponseCacheStore],
) -> None:
    """Keys compare as the field tuple - flattening would let crafted values collide across boundaries."""
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
    store = make_store()
    key = CacheKey("tools/list")
    await store.set(key, _entry("first"))
    await store.set(key, _entry("second"))
    assert await store.get(key) == _entry("second")


@store_contract
async def test_delete_removes_only_the_given_key(make_store: Callable[[], ResponseCacheStore]) -> None:
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
    """The SDK issues unconditional deletes during eviction, so deleting an absent key must be a no-op."""
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
    config = CacheConfig()
    assert config.store is None
    assert config.partition == ""
    assert config.target_id is None
    assert config.default_ttl_ms == 0
    assert config.clock is time.time
    assert config.share_public is False


def test_a_custom_store_without_a_partition_is_rejected_at_construction() -> None:
    """A custom store is shareable, so a missing partition would let private entries cross principals."""
    with pytest.raises(ValueError) as exc:
        CacheConfig(store=InMemoryResponseCacheStore())
    assert str(exc.value) == snapshot("a custom store requires an explicit partition")


def test_a_custom_store_with_an_explicit_partition_constructs() -> None:
    store = InMemoryResponseCacheStore()
    config = CacheConfig(store=store, partition="token-subject-1")
    assert config.store is store
    assert config.partition == "token-subject-1"


def test_an_empty_target_id_is_rejected_at_construction() -> None:
    """An empty target_id would collapse distinct servers onto the one shared sha256("") identity."""
    with pytest.raises(ValueError) as exc:
        CacheConfig(target_id="")
    assert str(exc.value) == snapshot("target_id must be a non-empty string or omitted")


def test_a_negative_default_ttl_is_rejected_at_construction() -> None:
    """A configured negative TTL is a programming error; negative wire ttlMs is tolerated as 0 at the parse seam."""
    with pytest.raises(ValueError) as exc:
        CacheConfig(default_ttl_ms=-1)
    assert str(exc.value) == snapshot("default_ttl_ms must be >= 0, got -1")


# --- InMemoryResponseCacheStore LRU cap ---


async def test_a_new_entry_past_the_cap_evicts_the_least_recently_used_one() -> None:
    store = InMemoryResponseCacheStore(max_entries=2)
    await store.set(_read_key("file:///a"), _entry("a"))
    await store.set(_read_key("file:///b"), _entry("b"))
    await store.set(_read_key("file:///c"), _entry("c"))
    assert await store.get(_read_key("file:///a")) is None
    assert await store.get(_read_key("file:///b")) == _entry("b")
    assert await store.get(_read_key("file:///c")) == _entry("c")


async def test_a_get_refreshes_an_entrys_recency() -> None:
    """Eviction order is recency (LRU), not insertion order: serving an entry keeps it alive."""
    store = InMemoryResponseCacheStore(max_entries=2)
    await store.set(_read_key("file:///a"), _entry("a"))
    await store.set(_read_key("file:///b"), _entry("b"))
    assert await store.get(_read_key("file:///a")) == _entry("a")  # a is now the most recent
    await store.set(_read_key("file:///c"), _entry("c"))  # evicts b, not a
    assert await store.get(_read_key("file:///a")) == _entry("a")
    assert await store.get(_read_key("file:///b")) is None
    assert await store.get(_read_key("file:///c")) == _entry("c")


async def test_replacing_an_entry_at_the_cap_refreshes_its_recency_without_evicting() -> None:
    store = InMemoryResponseCacheStore(max_entries=2)
    await store.set(_read_key("file:///a"), _entry("a"))
    await store.set(_read_key("file:///b"), _entry("b"))
    await store.set(_read_key("file:///a"), _entry("a-replaced"))  # still two entries; a is now the most recent
    await store.set(_read_key("file:///c"), _entry("c"))  # evicts b
    assert await store.get(_read_key("file:///a")) == _entry("a-replaced")
    assert await store.get(_read_key("file:///b")) is None
    assert await store.get(_read_key("file:///c")) == _entry("c")


async def test_a_touched_list_entry_survives_read_key_churn_through_the_cap() -> None:
    """The reason the cap is LRU over all entries: a hot list singleton each principal
    keeps re-reading must survive churn from per-uri resources/read keys."""
    store = InMemoryResponseCacheStore(max_entries=3)
    await store.set(CacheKey("tools/list"), _entry("tools"))
    for i in range(10):
        assert await store.get(CacheKey("tools/list")) == _entry("tools")  # each serve re-touches it
        await store.set(_read_key(f"file:///{i}"), _entry(i))
    assert await store.get(CacheKey("tools/list")) == _entry("tools")


async def test_a_zero_cap_disables_eviction() -> None:
    store = InMemoryResponseCacheStore(max_entries=0)
    uris = [f"file:///{i}" for i in range(5)]
    for uri in uris:
        await store.set(_read_key(uri), _entry(uri))
    for uri in uris:
        assert await store.get(_read_key(uri)) == _entry(uri)


async def test_deleting_an_entry_frees_its_cap_slot() -> None:
    store = InMemoryResponseCacheStore(max_entries=1)
    await store.set(_read_key("file:///a"), _entry("a"))
    await store.delete(_read_key("file:///a"))
    await store.set(_read_key("file:///b"), _entry("b"))
    assert await store.get(_read_key("file:///b")) == _entry("b")


def test_a_negative_cap_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError) as exc:
        InMemoryResponseCacheStore(max_entries=-1)
    assert str(exc.value) == snapshot("max_entries must be >= 0, got -1")


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
    store_cleanup_timeout: float = 5,
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
        store_cleanup_timeout=store_cleanup_timeout,
    )


def _private_arm(arm_id: str = "arm", partition: str = "", era: str | None = MODERN_VERSION) -> str:
    return json.dumps(["private", era, arm_id, partition])


def _public_arm(arm_id: str = "arm", partition: str = "", era: str | None = MODERN_VERSION) -> str:
    return json.dumps(["public", era, arm_id, partition])


def _wire_result(ttl_ms: int | None = None, cache_scope: str | None = None) -> ListToolsResult:
    """A wire-parsed `tools/list` result; `None` keeps the hint out of `model_fields_set`."""
    payload: dict[str, Any] = {"tools": []}
    if ttl_ms is not None:
        payload["ttlMs"] = ttl_ms
    if cache_scope is not None:
        payload["cacheScope"] = cache_scope
    return ListToolsResult.model_validate(payload)


def _read_result(ttl_ms: int) -> ReadResourceResult:
    return ReadResourceResult.model_validate({"contents": [], "ttlMs": ttl_ms})


class _ScriptedStore:
    """Logs `(op, key)` and awaits one-shot hooks around commits, modelling an async store mid-commit."""

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
    """Operations raise while their flag is set; toggling a flag models recovery."""

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
    """`delete` raises only for keys on the given arm, modelling a failed opposite-arm cleanup."""

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


# The lax pragmas here and in the wedged-store tests: 3.11's settrace-based coverage loses
# tracing in frames resumed after the coordinator's bounded-shield cleanup cancellation.
class _WedgingDeleteStore:
    """Once `wedged` flips, every `delete` blocks forever (an Event nothing sets),
    modelling a remote store with no socket timeout of its own."""

    before_set_commits: Callable[[], Awaitable[None]]
    """Awaited before `set` commits; assigned by the one test whose write reaches `set`."""

    def __init__(self, *, wedged: bool = False) -> None:
        self.inner = InMemoryResponseCacheStore()
        self.wedged = wedged
        self.deletes_started = 0

    async def get(self, key: CacheKey) -> CacheEntry | None:
        raise NotImplementedError

    async def set(self, key: CacheKey, entry: CacheEntry) -> None:
        await self.before_set_commits()
        await self.inner.set(key, entry)  # pragma: lax no cover

    async def delete(self, key: CacheKey) -> None:
        self.deletes_started += 1
        if self.wedged:
            await anyio.Event().wait()
        await self.inner.delete(key)

    async def clear(self) -> None:
        raise NotImplementedError


class _RehydratingStore:
    """`get` returns whatever a persistent store's deserializer produced - not necessarily what `set` received."""

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
    """The hints are 2026-07-28 assertions a legacy peer can still inject onto the wire (unknown keys
    reach `model_fields_set`), so on a non-modern session every result is treated as hint-absent."""
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store, version=version)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000, cache_scope="public"), gen, "use")
    assert await cache.read("tools/list", "") is None
    assert await store.get(CacheKey("tools/list", "", _private_arm(era=version))) is None
    assert await store.get(CacheKey("tools/list", "", _public_arm(era=version))) is None


async def test_a_legacy_session_with_a_default_ttl_caches_on_the_private_arm_only() -> None:
    """The operator's default TTL still applies on legacy sessions; injected hints cannot promote or re-clock."""
    store = InMemoryResponseCacheStore()
    clock = _ManualClock()
    cache = _coordinator(store, version=LEGACY_VERSION, default_ttl_ms=60_000, clock=clock)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=5, cache_scope="public"), gen, "use")
    private_entry = await store.get(CacheKey("tools/list", "", _private_arm(era=LEGACY_VERSION)))
    assert private_entry is not None
    assert private_entry.scope == "private"
    assert await store.get(CacheKey("tools/list", "", _public_arm(era=LEGACY_VERSION))) is None
    clock.now += 1.0  # well past the injected 5ms; the default 60s governs
    assert await cache.read("tools/list", "") == _wire_result(ttl_ms=5, cache_scope="public")


async def test_entries_never_cross_negotiated_eras_on_a_shared_store() -> None:
    """Arms fold in the negotiated version: the same listing genuinely differs by era
    (the SDK strips the 2026 fields for legacy sessions), so a 2025-negotiated session
    is never served an entry a 2026 session wrote - on either arm - nor vice versa."""
    store = InMemoryResponseCacheStore()
    modern = _coordinator(store, partition="p", default_ttl_ms=60_000)
    legacy = _coordinator(store, partition="p", version=LEGACY_VERSION, default_ttl_ms=60_000)

    gen = modern.capture("tools/list", "")
    await modern.write("tools/list", "", _wire_result(ttl_ms=60_000, cache_scope="public"), gen, "use")  # public arm
    private_result = ListPromptsResult.model_validate({"prompts": [], "ttlMs": 60_000})
    gen = modern.capture("prompts/list", "")
    await modern.write("prompts/list", "", private_result, gen, "use")  # private arm
    assert await legacy.read("tools/list", "") is None
    assert await legacy.read("prompts/list", "") is None

    gen = legacy.capture("resources/read", "file:///a")
    await legacy.write("resources/read", "file:///a", _read_result(ttl_ms=60_000), gen, "use")
    assert await legacy.read("resources/read", "file:///a") is not None  # cached for legacy itself...
    assert await modern.read("resources/read", "file:///a") is None  # ...but invisible across the era boundary


async def test_coordinators_negotiating_the_same_era_share_entries_through_the_store() -> None:
    """Era scoping splits eras only: same-era clients sharing a store still share both arms."""
    store = InMemoryResponseCacheStore()
    writer = _coordinator(store, partition="p")
    reader = _coordinator(store, partition="p")

    gen = writer.capture("tools/list", "")
    await writer.write("tools/list", "", _wire_result(ttl_ms=60_000, cache_scope="public"), gen, "use")
    private_result = ListPromptsResult.model_validate({"prompts": [], "ttlMs": 60_000})
    gen = writer.capture("prompts/list", "")
    await writer.write("prompts/list", "", private_result, gen, "use")

    assert await reader.read("tools/list", "") == _wire_result(ttl_ms=60_000, cache_scope="public")
    assert await reader.read("prompts/list", "") == private_result


# --- Coordinator: TTL and scope resolution ---


async def test_an_explicit_zero_ttl_is_not_overridden_by_the_default_ttl() -> None:
    """Spec-mandated: ttlMs 0 means immediately stale; the default fills in only for hint-absent results."""
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store, default_ttl_ms=60_000)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=0), gen, "use")
    assert await store.get(CacheKey("tools/list", "", _private_arm())) is None
    assert await store.get(CacheKey("tools/list", "", _public_arm())) is None


async def test_a_hint_absent_modern_result_uses_the_default_ttl_privately() -> None:
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
    """SEP-2549 hardening: a server cannot pin an entry beyond `MAX_TTL_MS`."""
    store = InMemoryResponseCacheStore()
    clock = _ManualClock()
    cache = _coordinator(store, clock=clock)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=7 * MAX_TTL_MS), gen, "use")
    entry = await store.get(CacheKey("tools/list", "", _private_arm()))
    assert entry is not None
    assert entry.expires_at == clock.now + MAX_TTL_MS / 1000


async def test_a_public_result_lands_on_the_public_arm_and_clears_the_private_arm() -> None:
    """On a scope flip, writing the new arm deletes the other so the two arms never both answer."""
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
    """Arm strings are cross-process store key material; changing their layout breaks shared stores."""
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store, partition="tenant-a", arm_id="abc123", default_ttl_ms=60_000)
    assert cache._arm("private") == snapshot('["private", "2026-07-28", "abc123", "tenant-a"]')
    assert cache._arm("public") == snapshot('["public", "2026-07-28", "abc123", "tenant-a"]')
    shared = _coordinator(store, partition="tenant-a", arm_id="abc123", share_public=True)
    assert shared._arm("public") == snapshot('["public", "2026-07-28", "abc123"]')
    # And entries genuinely land under those strings.
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(), gen, "use")
    assert await store.get(CacheKey("tools/list", "", '["private", "2026-07-28", "abc123", "tenant-a"]')) is not None
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000, cache_scope="public"), gen, "use")
    assert await store.get(CacheKey("tools/list", "", '["public", "2026-07-28", "abc123", "tenant-a"]')) is not None
    gen = shared.capture("tools/list", "")
    await shared.write("tools/list", "", _wire_result(ttl_ms=60_000, cache_scope="public"), gen, "use")
    assert await store.get(CacheKey("tools/list", "", '["public", "2026-07-28", "abc123"]')) is not None


async def test_public_entries_do_not_cross_partitions_by_default() -> None:
    """Security default (deviates from the TypeScript SDK): a server stamping per-tenant data public
    (bug or malice) cannot leak one tenant's response to another through a shared store."""
    store = InMemoryResponseCacheStore()
    tenant_a = _coordinator(store, partition="tenant-a")
    tenant_b = _coordinator(store, partition="tenant-b")
    gen = tenant_a.capture("tools/list", "")
    await tenant_a.write("tools/list", "", _wire_result(ttl_ms=60_000, cache_scope="public"), gen, "use")
    assert await tenant_a.read("tools/list", "") == _wire_result(ttl_ms=60_000, cache_scope="public")
    assert await tenant_b.read("tools/list", "") is None


async def test_share_public_serves_public_entries_across_partitions_but_never_private_ones() -> None:
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
    """Defense in depth against a corrupted or pre-seeded store: the arm routes, the entry's scope verifies."""
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store)
    await store.set(
        CacheKey("tools/list", "", _public_arm()),
        CacheEntry(value=_wire_result(), scope="private", expires_at=2_000_000.0),
    )
    assert await cache.read("tools/list", "") is None


async def test_a_stale_private_entry_does_not_shadow_a_fresh_public_one() -> None:
    """A stale private entry is an arm-probe miss, so the fall-through finds a public entry seeded by
    another client after a server scope flip."""
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
    """Entries rehydrated without expiry metadata are misses, not immortal."""
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store)
    await store.set(
        CacheKey("tools/list", "", _private_arm()),
        CacheEntry(value=_wire_result(), scope="private", expires_at=None),
    )
    assert await cache.read("tools/list", "") is None


# --- Coordinator: write ordering ---


async def test_write_deletes_the_opposite_arm_before_setting_its_own() -> None:
    """Delete-then-set: a cancellation between the two operations leaves a miss, never two answering arms."""
    store = _ScriptedStore()
    cache = _coordinator(store)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000, cache_scope="public"), gen, "use")
    assert store.ops == [
        ("delete", CacheKey("tools/list", "", _private_arm())),
        ("set", CacheKey("tools/list", "", _public_arm())),
    ]


async def test_an_eviction_landing_during_an_async_set_is_compensated() -> None:
    """TOCTOU re-check: the eviction's deletes see nothing (the set has not committed yet), so the
    post-set generation re-check must fire a compensating delete."""
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
    """The compensating delete is shielded: a timeout firing while the store's set is already on the
    wire must not resurrect the evicted entry for its full TTL."""
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
    """The refresh purge is shielded - a mid-purge cancellation must not leave the superseded opposite arm."""
    store = _ScriptedStore()
    cache = _coordinator(store)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000, cache_scope="public"), gen, "use")
    public_key = CacheKey("tools/list", "", _public_arm())
    assert await store.inner.get(public_key) is not None
    with anyio.CancelScope() as scope:
        scope.cancel()
        # Delivers at the first checkpoint after the private-arm delete commits.
        store.after_delete_commits = anyio.lowlevel.checkpoint
        await cache.write("tools/list", "", _wire_result(ttl_ms=0), gen, "refresh")
    assert await store.inner.get(public_key) is None


async def test_a_cancellation_during_an_eviction_still_evicts_both_arms() -> None:
    """Eviction's arm deletes are shielded - a notification task cancelled mid-eviction (session
    teardown) must not leave one arm serving the evicted entry."""
    store = _ScriptedStore()
    cache = _coordinator(store)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000, cache_scope="public"), gen, "use")
    public_key = CacheKey("tools/list", "", _public_arm())
    with anyio.CancelScope() as scope:
        scope.cancel()
        # Delivers at the first checkpoint after the private-arm delete commits.
        store.after_delete_commits = anyio.lowlevel.checkpoint
        await cache.evict_method("tools/list")
    assert await store.inner.get(public_key) is None


# --- Coordinator: bounded must-complete cleanup ---
# These tests inject a tiny `store_cleanup_timeout` because the bound itself is the
# behavior under test; the wedged delete only ever blocks for that injected bound.


async def test_evict_key_with_a_wedged_store_delete_returns_at_the_cleanup_bound(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A store delete that never completes cannot make eviction - and with it client
    teardown - hang uncancellably: the must-complete cleanup is bounded, the remaining
    deletes are abandoned, and the unreaped entries age out by TTL."""
    store = _WedgingDeleteStore(wedged=True)
    cache = _coordinator(store, store_cleanup_timeout=0.01)
    with caplog.at_level(logging.WARNING, logger="mcp.client.caching"), anyio.fail_after(5):
        await cache.evict_key("tools/list", "")
    assert store.deletes_started == 1  # pragma: lax no cover  # the second arm's delete was abandoned with the first
    assert caplog.messages == snapshot(  # pragma: lax no cover
        ["Response cache store delete timed out; the entry will age out by TTL"]
    )


async def test_a_refresh_purge_with_a_wedged_store_delete_returns_at_the_cleanup_bound() -> None:
    store = _WedgingDeleteStore(wedged=True)
    cache = _coordinator(store, store_cleanup_timeout=0.01)
    gen = cache.capture("tools/list", "")
    with anyio.fail_after(5):
        await cache.write("tools/list", "", _wire_result(ttl_ms=0), gen, "refresh")
    assert store.deletes_started == 1  # pragma: lax no cover


async def test_an_eviction_mid_set_with_a_wedged_store_delete_returns_at_the_cleanup_bound() -> None:
    """The post-set compensating delete is bounded like every other must-complete delete;
    the entry it could not reap stays in the store and ages out by TTL."""
    store = _WedgingDeleteStore()
    cache = _coordinator(store, store_cleanup_timeout=0.01)
    gen = cache.capture("tools/list", "")

    async def wedge_then_evict() -> None:
        store.wedged = True
        await cache.evict_method("tools/list")  # its own cleanup hits the bound too

    store.before_set_commits = wedge_then_evict
    with anyio.fail_after(5):
        await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen, "use")
    # Opposite-arm delete, the eviction's first delete, the compensating delete.
    assert store.deletes_started == 3  # pragma: lax no cover
    # The accepted degradation: the unreaped entry stays until its TTL expires.
    assert await store.inner.get(CacheKey("tools/list", "", _private_arm())) is not None  # pragma: lax no cover


# --- Coordinator: store error discipline ---


async def test_a_raising_store_get_is_a_cache_miss() -> None:
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
    """A persistent store has no method-to-model mapping, so its `get` may return serialized shapes;
    the warned miss is one burst, not one warning per cached read."""
    cache = _coordinator(_RehydratingStore(rehydrated))
    with caplog.at_level(logging.WARNING, logger="mcp.client.caching"):
        assert await cache.read("tools/list", "") is None
        assert await cache.read("tools/list", "") is None
    assert len(caplog.records) == 1


async def test_a_raising_opposite_arm_delete_aborts_the_write() -> None:
    """Setting after a failed opposite-arm delete could leave both arms populated."""
    store = _FailingStore(fail_delete=True)
    cache = _coordinator(store)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen, "use")
    assert await store.inner.get(CacheKey("tools/list", "", _private_arm())) is None
    assert await store.inner.get(CacheKey("tools/list", "", _public_arm())) is None


async def test_a_failed_opposite_arm_delete_degrades_the_key_to_a_full_miss() -> None:
    """The fetch superseded the warm own-arm entry, so it is best-effort deleted too; the write never raises."""
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
    store = _FailingStore(fail_set=True)
    cache = _coordinator(store)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen, "use")
    assert await cache.read("tools/list", "") is None


async def test_a_failed_set_purges_the_pre_existing_own_arm_entry() -> None:
    """The fetch superseded the warm own-arm entry, and the failed set left it in place:
    without the purge it would keep serving the superseded value for its full TTL."""
    store = _FailingStore()
    cache = _coordinator(store)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen, "use")
    assert await cache.read("tools/list", "") is not None  # the warm own-arm entry
    store.fail_set = True
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen, "use")  # the caller's fetch is unaffected
    assert await store.inner.get(CacheKey("tools/list", "", _private_arm())) is None
    assert await store.inner.get(CacheKey("tools/list", "", _public_arm())) is None
    assert await cache.read("tools/list", "") is None


async def test_eviction_with_a_raising_delete_still_bumps_the_generation() -> None:
    """Bump-first: a fetch captured before the eviction cannot write back even when the deletes raise."""
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
    """Bursts are tracked per operation kind - the healthy deletes between failing sets never re-arm."""
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
    """Spec-aligned: a fetch in flight when its key is evicted must not write the evicted entry back."""
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store)
    gen = cache.capture("tools/list", "")
    await cache.evict_method("tools/list")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen, "use")
    assert await store.get(CacheKey("tools/list", "", _private_arm())) is None
    assert await store.get(CacheKey("tools/list", "", _public_arm())) is None


async def test_recapturing_a_registered_key_returns_its_current_generation() -> None:
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store)
    gen_before = cache.capture("tools/list", "")
    await cache.evict_method("tools/list")
    gen_after = cache.capture("tools/list", "")
    assert gen_after != gen_before
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen_after, "use")
    assert await cache.read("tools/list", "") == _wire_result(ttl_ms=60_000)


async def test_the_generation_map_drops_the_oldest_key_at_its_cap() -> None:
    """A dropped key's race guard degrades to the accepted co-tenant class - an eviction racing its
    in-flight fetch goes undetected (cap is 4096 in production, parametrized small here)."""
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
    """The refetch superseded the warm entry, which must not be served again."""
    store = InMemoryResponseCacheStore()
    cache = _coordinator(store)
    gen = cache.capture("tools/list", "")
    await cache.write("tools/list", "", _wire_result(ttl_ms=60_000), gen, "use")
    assert await cache.read("tools/list", "") is not None
    await cache.write("tools/list", "", _wire_result(ttl_ms=0), gen, "refresh")
    assert await store.get(CacheKey("tools/list", "", _private_arm())) is None
    assert await store.get(CacheKey("tools/list", "", _public_arm())) is None


async def test_evict_key_on_an_unregistered_key_still_deletes_both_arms() -> None:
    """A persistent store may hold warm entries from a prior process this coordinator never captured."""
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
    """Spec SHOULD: notifications invalidate - and nothing beyond their mapped entries."""
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
