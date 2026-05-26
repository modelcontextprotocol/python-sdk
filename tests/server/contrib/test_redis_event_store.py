# pyright: reportUnknownParameterType=false
# pyright: reportMissingParameterType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownMemberType=false
"""Tests for RedisEventStore.

Uses fakeredis — no external Redis server required.
All tests are async (anyio/asyncio backend, set by tests/conftest.py).
"""

from __future__ import annotations

import asyncio
import logging

import fakeredis.aioredis as fakeredis
import pytest

from mcp.server.contrib.event_stores import RedisEventStore
from mcp.server.streamable_http import EventId, EventMessage, StreamId
from mcp.types import JSONRPCRequest

# ── Helpers ──────────────────────────────────────────────────────────────────

# A reusable JSONRPCMessage for tests that don't care about content
SAMPLE_MSG = JSONRPCRequest(jsonrpc="2.0", id="1", method="tools/list")


@pytest.fixture
async def redis_client():
    """FakeRedis is a real async-compatible in-process Redis emulator.
    Each test gets a fresh client (function scope = default).
    """
    client = fakeredis.FakeRedis()
    yield client


@pytest.fixture
def store(redis_client, recwarn):
    """ttl=None triggers a logger.warning.
    We suppress it via recwarn so tests don't fail on unexpected warnings.
    """
    return RedisEventStore(redis_client, key_prefix="test:", ttl=None)


@pytest.fixture
def store_with_ttl(redis_client):
    return RedisEventStore(redis_client, key_prefix="test:", ttl=60)


# ── Shared helper ─────────────────────────────────────────────────────────────


async def collect_events(
    store: RedisEventStore,
    last_event_id: EventId,
) -> tuple[list[EventMessage], StreamId | None]:
    captured: list[EventMessage] = []

    async def cb(event: EventMessage) -> None:
        captured.append(event)

    stream_id = await store.replay_events_after(last_event_id, cb)
    return captured, stream_id


# ─────────────────────────────────────────────────────────────────────────────
# store_event tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_store_event_returns_string_integer(store):
    id1 = await store.store_event("stream-A", SAMPLE_MSG)
    assert isinstance(id1, str)
    assert id1.isdigit()  # must be a parseable integer


@pytest.mark.anyio
async def test_store_event_ids_are_monotonically_increasing(store):
    id1 = await store.store_event("stream-A", SAMPLE_MSG)
    id2 = await store.store_event("stream-A", SAMPLE_MSG)
    id3 = await store.store_event("stream-B", SAMPLE_MSG)  # different stream

    # IDs must increase across streams too (global counter)
    assert int(id1) < int(id2) < int(id3)
    # First call always returns "1"
    assert id1 == "1"


@pytest.mark.anyio
async def test_store_priming_event_writes_empty_payload(store, redis_client):
    event_id = await store.store_event("stream-A", None)  # None = priming

    # Read directly from Redis to verify storage format
    raw = await redis_client.hget(f"test:event:{event_id}", "payload")
    assert raw == b""  # empty bytes, NOT b"null" or missing


@pytest.mark.anyio
async def test_store_event_writes_stream_id_to_hash(store, redis_client):
    event_id = await store.store_event("my-stream", SAMPLE_MSG)

    raw_stream = await redis_client.hget(f"test:event:{event_id}", "stream_id")
    assert raw_stream == b"my-stream"


@pytest.mark.anyio
async def test_store_event_adds_to_sorted_set(store, redis_client):
    id1 = await store.store_event("stream-A", SAMPLE_MSG)
    id2 = await store.store_event("stream-A", SAMPLE_MSG)

    # Both event IDs must appear in the stream's sorted set
    members = await redis_client.zrange("test:stream:stream-A", 0, -1)
    decoded = [m.decode() for m in members]
    assert id1 in decoded
    assert id2 in decoded
    # Sorted by score (ascending) = ascending by event_id int value
    assert decoded.index(id1) < decoded.index(id2)


@pytest.mark.anyio
async def test_concurrent_store_event_produces_unique_ids(store):
    # Fire 50 concurrent store_event calls — INCR must be collision-free
    tasks = [asyncio.create_task(store.store_event("stream-X", SAMPLE_MSG)) for _ in range(50)]
    ids = await asyncio.gather(*tasks)

    # All 50 IDs must be distinct
    assert len(set(ids)) == 50
    # Every ID must be a valid integer string
    assert all(id_.isdigit() for id_ in ids)


# ─────────────────────────────────────────────────────────────────────────────
# replay_events_after tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_replay_unknown_id_returns_none(store):
    events, stream_id = await collect_events(store, "9999")
    assert stream_id is None
    assert events == []


@pytest.mark.anyio
async def test_replay_returns_correct_stream_id(store):
    anchor = await store.store_event("my-stream", SAMPLE_MSG)
    # No further events stored

    events, stream_id = await collect_events(store, anchor)
    assert stream_id == "my-stream"
    assert events == []  # nothing after anchor


@pytest.mark.anyio
async def test_replay_skips_priming_events(store):
    anchor = await store.store_event("stream-A", SAMPLE_MSG)  # real event
    _ = await store.store_event("stream-A", None)  # priming
    id3 = await store.store_event("stream-A", SAMPLE_MSG)  # real event

    events, _ = await collect_events(store, anchor)

    # Priming must be invisible — only id3 appears
    assert len(events) == 1
    assert events[0].event_id == id3


@pytest.mark.anyio
async def test_replay_skips_expired_event_payloads(store, redis_client):
    anchor = await store.store_event("stream-A", SAMPLE_MSG)
    id2 = await store.store_event("stream-A", SAMPLE_MSG)
    id3 = await store.store_event("stream-A", SAMPLE_MSG)

    # Manually delete the event key for id2 from Redis, but keep it in the sorted set
    await redis_client.delete(f"test:event:{id2}")

    events, _ = await collect_events(store, anchor)

    # Replay should skip id2 (since its payload was deleted/expired) and return only id3
    assert len(events) == 1
    assert events[0].event_id == id3


@pytest.mark.anyio
async def test_replay_events_are_in_ascending_order(store):
    anchor = await store.store_event("stream-A", SAMPLE_MSG)
    id2 = await store.store_event("stream-A", SAMPLE_MSG)
    id3 = await store.store_event("stream-A", SAMPLE_MSG)

    events, _ = await collect_events(store, anchor)

    # Must come back in ascending ID order
    assert len(events) == 2
    assert events[0].event_id == id2
    assert events[1].event_id == id3


@pytest.mark.anyio
async def test_replay_excludes_anchor_event_itself(store):
    anchor = await store.store_event("stream-A", SAMPLE_MSG)
    id2 = await store.store_event("stream-A", SAMPLE_MSG)

    events, _ = await collect_events(store, anchor)

    # anchor itself must NOT be replayed — only events strictly after it
    event_ids = [e.event_id for e in events]
    assert anchor not in event_ids
    assert id2 in event_ids


@pytest.mark.anyio
async def test_replay_stream_isolation(store):
    # anchor belongs to stream-A
    anchor = await store.store_event("stream-A", SAMPLE_MSG)

    # store events on stream-B — must NOT appear in stream-A's replay
    _ = await store.store_event("stream-B", SAMPLE_MSG)
    _ = await store.store_event("stream-B", SAMPLE_MSG)

    # more events on stream-A
    id4 = await store.store_event("stream-A", SAMPLE_MSG)

    events, stream_id = await collect_events(store, anchor)

    assert stream_id == "stream-A"
    assert len(events) == 1  # only id4, not stream-B events
    assert events[0].event_id == id4


@pytest.mark.anyio
async def test_replay_message_content_round_trips(store):
    original = JSONRPCRequest(jsonrpc="2.0", id="99", method="resources/list")
    anchor = await store.store_event("stream-A", original)
    await store.store_event("stream-A", original)

    events, _ = await collect_events(store, anchor)

    assert len(events) == 1
    # The deserialized message must match the original
    replayed = events[0].message
    assert isinstance(replayed, JSONRPCRequest)
    assert replayed.method == "resources/list"
    assert replayed.id == "99"


@pytest.mark.anyio
async def test_replay_event_id_is_attached_to_event_message(store):
    anchor = await store.store_event("stream-A", SAMPLE_MSG)
    id2 = await store.store_event("stream-A", SAMPLE_MSG)

    events, _ = await collect_events(store, anchor)

    # event_id must be set on EventMessage so the client can use it
    # as a resumption token
    assert events[0].event_id == id2


# ─────────────────────────────────────────────────────────────────────────────
# TTL tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_event_key_has_ttl_when_configured(store_with_ttl, redis_client):
    event_id = await store_with_ttl.store_event("stream-A", SAMPLE_MSG)

    ttl = await redis_client.ttl(f"test:event:{event_id}")
    # TTL should be set and positive (allow execution delay on slow runners)
    assert 0 < ttl <= 60


@pytest.mark.anyio
async def test_stream_key_has_ttl_when_configured(store_with_ttl, redis_client):
    await store_with_ttl.store_event("stream-A", SAMPLE_MSG)

    ttl = await redis_client.ttl("test:stream:stream-A")
    # TTL should be set and positive (allow execution delay on slow runners)
    assert 0 < ttl <= 60


@pytest.mark.anyio
async def test_counter_key_has_ttl_when_configured(store_with_ttl, redis_client):
    await store_with_ttl.store_event("stream-A", SAMPLE_MSG)

    ttl = await redis_client.ttl("test:counter")
    # TTL should be set and positive (allow execution delay on slow runners)
    assert 0 < ttl <= 60


@pytest.mark.anyio
async def test_no_ttl_on_keys_when_not_configured(store, redis_client):
    event_id = await store.store_event("stream-A", SAMPLE_MSG)

    event_ttl = await redis_client.ttl(f"test:event:{event_id}")
    stream_ttl = await redis_client.ttl("test:stream:stream-A")
    counter_ttl = await redis_client.ttl("test:counter")

    # Redis returns -1 for keys that exist but have no TTL
    assert event_ttl == -1
    assert stream_ttl == -1
    assert counter_ttl == -1


# ─────────────────────────────────────────────────────────────────────────────
# Key prefix test
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_custom_key_prefix_isolates_two_stores(redis_client, recwarn):
    store_a = RedisEventStore(redis_client, key_prefix="server-a:", ttl=None)
    store_b = RedisEventStore(redis_client, key_prefix="server-b:", ttl=None)

    id_a = await store_a.store_event("stream-1", SAMPLE_MSG)
    id_b = await store_b.store_event("stream-1", SAMPLE_MSG)

    # Both stores start from their OWN counter — both return "1"
    assert id_a == "1"
    assert id_b == "1"

    # Keys from store-a must not appear under server-b: prefix
    a_keys = [k.decode() for k in await redis_client.keys("server-a:*")]
    b_keys = [k.decode() for k in await redis_client.keys("server-b:*")]

    assert all("server-b:" not in k for k in a_keys)
    assert all("server-a:" not in k for k in b_keys)

    # Replaying on store_a must NOT pick up store_b's events
    events_a, stream_id_a = await collect_events(store_a, id_a)
    assert stream_id_a == "stream-1"
    assert events_a == []  # nothing after anchor on store_a


# ─────────────────────────────────────────────────────────────────────────────
# Warning / logging tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_no_ttl_emits_log_warning(redis_client, caplog):
    with caplog.at_level(logging.WARNING, logger="mcp.server.contrib.event_stores.redis"):
        RedisEventStore(redis_client, ttl=None)

    assert any("ttl=None" in record.message for record in caplog.records)


@pytest.mark.anyio
async def test_with_ttl_no_warning_emitted(redis_client, caplog):
    with caplog.at_level(logging.WARNING, logger="mcp.server.contrib.event_stores.redis"):
        RedisEventStore(redis_client, ttl=3600)

    # No warning should appear when TTL is configured
    assert not any("ttl" in record.message.lower() for record in caplog.records)
