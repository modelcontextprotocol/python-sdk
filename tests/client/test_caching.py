"""`mcp.client.caching`: the `CacheConfig` construction guards, the store
contract every `ResponseCacheStore` implementation must satisfy, and the
default in-memory store's bounded `resources/read` FIFO.

The store-contract tests are parametrized over `STORE_FACTORIES`; a
third-party store implementation can be run against the same contract by
adding its factory to the list (or copying the parametrization).
"""

import time
from collections.abc import Callable
from typing import Any

import pytest
from inline_snapshot import snapshot

from mcp.client.caching import (
    CacheConfig,
    CacheEntry,
    CacheKey,
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
