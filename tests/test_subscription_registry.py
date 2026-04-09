"""Tests for SubscriptionRegistry and RetainedValueStore."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mcp.server.events import RetainedValueStore, SubscriptionRegistry
from mcp.types import RetainedEvent


@pytest.fixture
def registry():
    return SubscriptionRegistry()


@pytest.fixture
def store():
    return RetainedValueStore()


@pytest.mark.anyio
class TestSubscriptionRegistry:
    async def test_exact_match(self, registry: SubscriptionRegistry):
        await registry.add("s1", "a/b/c")
        assert await registry.match("a/b/c") == {"s1"}
        assert await registry.match("a/b/d") == set()

    async def test_plus_wildcard_matches_single_segment(self, registry: SubscriptionRegistry):
        await registry.add("s1", "a/+/c")
        assert await registry.match("a/x/c") == {"s1"}
        assert await registry.match("a/y/c") == {"s1"}
        # + does NOT match multiple segments
        assert await registry.match("a/x/y/c") == set()
        # + does NOT match empty segment (no segment)
        assert await registry.match("a//c") == set()

    async def test_hash_wildcard_matches_trailing(self, registry: SubscriptionRegistry):
        await registry.add("s1", "a/#")
        assert await registry.match("a/b") == {"s1"}
        assert await registry.match("a/b/c/d") == {"s1"}
        assert await registry.match("a/") == {"s1"}
        # Must start with a/
        assert await registry.match("b/c") == set()

    async def test_hash_only_valid_as_last_segment(self):
        from mcp.server.events import _pattern_to_regex

        with pytest.raises(ValueError, match="only valid as the last segment"):
            _pattern_to_regex("a/#/b")

    async def test_at_most_once_delivery(self, registry: SubscriptionRegistry):
        """A session with overlapping patterns should appear only once."""
        await registry.add("s1", "a/+")
        await registry.add("s1", "a/#")
        # Both patterns match "a/b", but s1 should only appear once
        result = await registry.match("a/b")
        assert result == {"s1"}

    async def test_multiple_sessions(self, registry: SubscriptionRegistry):
        await registry.add("s1", "a/b")
        await registry.add("s2", "a/b")
        await registry.add("s3", "x/y")
        assert await registry.match("a/b") == {"s1", "s2"}
        assert await registry.match("x/y") == {"s3"}

    async def test_remove(self, registry: SubscriptionRegistry):
        await registry.add("s1", "a/b")
        await registry.add("s1", "c/d")
        await registry.remove("s1", "a/b")
        assert await registry.match("a/b") == set()
        assert await registry.match("c/d") == {"s1"}

    async def test_remove_all(self, registry: SubscriptionRegistry):
        await registry.add("s1", "a/b")
        await registry.add("s1", "c/d")
        await registry.remove_all("s1")
        assert await registry.match("a/b") == set()
        assert await registry.match("c/d") == set()

    async def test_get_subscriptions(self, registry: SubscriptionRegistry):
        await registry.add("s1", "a/b")
        await registry.add("s1", "c/+")
        subs = await registry.get_subscriptions("s1")
        assert subs == {"a/b", "c/+"}

    async def test_get_subscriptions_empty(self, registry: SubscriptionRegistry):
        subs = await registry.get_subscriptions("nonexistent")
        assert subs == set()

    async def test_remove_nonexistent(self, registry: SubscriptionRegistry):
        """Removing a non-existent subscription should not raise."""
        await registry.remove("s1", "a/b")  # no error

    async def test_hash_matches_zero_segments(self, registry: SubscriptionRegistry):
        """# should match zero trailing segments (just the prefix)."""
        await registry.add("s1", "a/#")
        # "a/" has an empty trailing segment, which # should match
        assert await registry.match("a/") == {"s1"}

    async def test_rejects_pattern_exceeding_max_depth(self, registry: SubscriptionRegistry):
        """Patterns with more than 8 segments should be rejected."""
        # Exactly 8 segments should be fine
        await registry.add("s1", "a/b/c/d/e/f/g/h")
        assert await registry.match("a/b/c/d/e/f/g/h") == {"s1"}

        # 9 segments should raise
        with pytest.raises(ValueError, match="exceeds maximum depth of 8 segments"):
            await registry.add("s1", "a/b/c/d/e/f/g/h/i")

    async def test_hash_root_wildcard_matches_everything(self, registry: SubscriptionRegistry):
        """Pattern '#' (sole segment) should match any topic."""
        await registry.add("s1", "#")
        assert await registry.match("any/topic/at/all") == {"s1"}
        assert await registry.match("single") == {"s1"}
        assert await registry.match("a/b") == {"s1"}

    async def test_hash_matches_zero_trailing_no_slash(self, registry: SubscriptionRegistry):
        """# should match the prefix with no trailing slash (zero segments after prefix).

        Per MQTT spec, 'myapp/#' should match 'myapp' itself.
        """
        await registry.add("s1", "myapp/#")
        assert await registry.match("myapp") == {"s1"}
        # Also still matches one or more trailing segments
        assert await registry.match("myapp/foo") == {"s1"}
        assert await registry.match("myapp/foo/bar") == {"s1"}


@pytest.mark.anyio
class TestRetainedValueStore:
    async def test_set_and_get(self, store: RetainedValueStore):
        event = RetainedEvent(topic="a/b", eventId="e1", payload="val")
        await store.set("a/b", event)
        assert await store.get("a/b") == event

    async def test_get_missing(self, store: RetainedValueStore):
        assert await store.get("nonexistent") is None

    async def test_overwrite(self, store: RetainedValueStore):
        e1 = RetainedEvent(topic="a/b", eventId="e1", payload="old")
        e2 = RetainedEvent(topic="a/b", eventId="e2", payload="new")
        await store.set("a/b", e1)
        await store.set("a/b", e2)
        assert await store.get("a/b") == e2

    async def test_delete(self, store: RetainedValueStore):
        event = RetainedEvent(topic="a/b", eventId="e1", payload="val")
        await store.set("a/b", event)
        await store.delete("a/b")
        assert await store.get("a/b") is None

    async def test_delete_nonexistent(self, store: RetainedValueStore):
        await store.delete("nonexistent")  # no error

    async def test_get_matching(self, store: RetainedValueStore):
        e1 = RetainedEvent(topic="a/x", eventId="e1", payload="v1")
        e2 = RetainedEvent(topic="a/y", eventId="e2", payload="v2")
        e3 = RetainedEvent(topic="b/x", eventId="e3", payload="v3")
        await store.set("a/x", e1)
        await store.set("a/y", e2)
        await store.set("b/x", e3)
        matching = await store.get_matching("a/+")
        assert len(matching) == 2
        topics = {e.topic for e in matching}
        assert topics == {"a/x", "a/y"}
        by_topic = {e.topic: e for e in matching}
        assert by_topic["a/x"].event_id == "e1"
        assert by_topic["a/x"].payload == "v1"
        assert by_topic["a/y"].event_id == "e2"
        assert by_topic["a/y"].payload == "v2"

    async def test_expired_not_returned(self, store: RetainedValueStore):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        event = RetainedEvent(topic="a/b", eventId="e1", payload="val")
        await store.set("a/b", event, expires_at=past)
        assert await store.get("a/b") is None

    async def test_not_expired_returned(self, store: RetainedValueStore):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        event = RetainedEvent(topic="a/b", eventId="e1", payload="val")
        await store.set("a/b", event, expires_at=future)
        assert await store.get("a/b") == event

    async def test_get_matching_reuses_cached_regex(self, store: RetainedValueStore):
        """Second call with same pattern should reuse cached compiled regex."""
        e1 = RetainedEvent(topic="a/x", eventId="e1", payload="v1")
        await store.set("a/x", e1)
        # First call compiles and caches
        first = await store.get_matching("a/+")
        assert len(first) == 1
        # Second call hits the cache branch (skips compile)
        second = await store.get_matching("a/+")
        assert len(second) == 1
        assert second[0].topic == "a/x"

    async def test_invalid_expires_at_treated_as_not_expired(self, store: RetainedValueStore):
        """Malformed ``expires_at`` should be treated as not expired rather than raising."""
        event = RetainedEvent(topic="a/b", eventId="e1", payload="val")
        await store.set("a/b", event, expires_at="not-a-valid-iso-timestamp")
        # Parsing fails (ValueError), so _is_expired returns False and the value is returned.
        assert await store.get("a/b") == event

    async def test_naive_expires_at_assumed_utc(self, store: RetainedValueStore):
        """A naive (tz-less) ISO timestamp should be interpreted as UTC.

        Exercises the ``if expiry.tzinfo is None`` branch in ``_is_expired``.
        """
        # Naive timestamp in the future (no timezone suffix).
        future_naive = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None).isoformat()
        event = RetainedEvent(topic="a/b", eventId="e1", payload="val")
        await store.set("a/b", event, expires_at=future_naive)
        # Interpreted as UTC -> not expired -> returned.
        assert await store.get("a/b") == event

        # Naive timestamp in the past -> expired -> None.
        past_naive = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None).isoformat()
        event2 = RetainedEvent(topic="c/d", eventId="e2", payload="val2")
        await store.set("c/d", event2, expires_at=past_naive)
        assert await store.get("c/d") is None

    async def test_expired_cleaned_on_get_matching(self, store: RetainedValueStore):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        e1 = RetainedEvent(topic="a/x", eventId="e1", payload="expired")
        e2 = RetainedEvent(topic="a/y", eventId="e2", payload="valid")
        await store.set("a/x", e1, expires_at=past)
        await store.set("a/y", e2, expires_at=future)
        matching = await store.get_matching("a/+")
        assert len(matching) == 1
        assert matching[0].topic == "a/y"
        assert matching[0].event_id == "e2"
        assert matching[0].payload == "valid"
