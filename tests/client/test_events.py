"""Tests for client-side event utilities: ProvenanceEnvelope and EventQueue."""

from __future__ import annotations

from mcp.client.events import EventQueue, ProvenanceEnvelope
from mcp.types import EventEffect, EventParams


# ---------------------------------------------------------------------------
# ProvenanceEnvelope
# ---------------------------------------------------------------------------


class TestProvenanceEnvelope:
    def test_to_dict_all_fields(self) -> None:
        env = ProvenanceEnvelope(
            server="ci-server",
            server_trust="configured",
            topic="builds/myapp/status",
            source="ci/jenkins",
            event_id="evt_a1b2c3d4",
            received_at="2026-04-09T14:30:00Z",
        )
        d = env.to_dict()
        assert d == {
            "server": "ci-server",
            "server_trust": "configured",
            "topic": "builds/myapp/status",
            "source": "ci/jenkins",
            "event_id": "evt_a1b2c3d4",
            "received_at": "2026-04-09T14:30:00Z",
        }

    def test_to_dict_optional_none(self) -> None:
        env = ProvenanceEnvelope(
            server="my-server",
            server_trust="unknown",
            topic="test/topic",
        )
        d = env.to_dict()
        assert d == {
            "server": "my-server",
            "server_trust": "unknown",
            "topic": "test/topic",
        }
        assert "source" not in d
        assert "event_id" not in d
        assert "received_at" not in d

    def test_to_xml_basic(self) -> None:
        env = ProvenanceEnvelope(
            server="spellbook",
            server_trust="trusted",
            topic="spellbook/sessions/abc/messages",
            source="tool/messaging_send",
        )
        xml = env.to_xml('{"text": "hello"}')
        assert xml.startswith("<mcp:event ")
        assert 'server="spellbook"' in xml
        assert 'server_trust="trusted"' in xml
        assert 'topic="spellbook/sessions/abc/messages"' in xml
        assert 'source="tool/messaging_send"' in xml
        assert '{"text": "hello"}</mcp:event>' in xml

    def test_to_xml_empty_payload(self) -> None:
        env = ProvenanceEnvelope(
            server="s", server_trust="t", topic="x"
        )
        xml = env.to_xml()
        assert xml.endswith("></mcp:event>")

    def test_to_xml_with_special_chars_in_payload(self) -> None:
        env = ProvenanceEnvelope(
            server="s", server_trust="t", topic="x"
        )
        xml = env.to_xml('<script>alert("xss")</script>')
        # Payload body must be escaped
        assert "<script>" not in xml
        assert "&lt;script&gt;" in xml

    def test_to_xml_with_special_chars_in_attrs(self) -> None:
        env = ProvenanceEnvelope(
            server='evil"server',
            server_trust="t",
            topic="x<y",
        )
        xml = env.to_xml("payload")
        # Attribute values must be quoted safely (no raw " or <)
        assert 'server="evil"server"' not in xml
        # quoteattr will use &quot; or switch to single-quote wrapping
        assert "payload</mcp:event>" in xml

    def test_from_event_extracts_fields(self) -> None:
        event = EventParams(
            topic="builds/status",
            eventId="evt_123",
            payload={"status": "ok"},
            source="ci/jenkins",
        )
        env = ProvenanceEnvelope.from_event(
            event, server="ci-server", server_trust="configured"
        )
        assert env.server == "ci-server"
        assert env.server_trust == "configured"
        assert env.topic == "builds/status"
        assert env.source == "ci/jenkins"
        assert env.event_id == "evt_123"
        assert env.received_at is not None
        # received_at should be a valid ISO 8601 string
        assert "T" in env.received_at

    def test_from_event_no_source(self) -> None:
        event = EventParams(
            topic="test/topic",
            eventId="evt_456",
            payload={},
        )
        env = ProvenanceEnvelope.from_event(
            event, server="srv", server_trust="unknown"
        )
        assert env.source is None


# ---------------------------------------------------------------------------
# EventQueue
# ---------------------------------------------------------------------------


def _make_event(
    topic: str = "t",
    effects: list[EventEffect] | None = None,
) -> EventParams:
    """Helper to create a minimal EventParams for queue tests."""
    return EventParams(
        topic=topic,
        eventId="e1",
        payload={},
        requestedEffects=effects,
    )


class TestEventQueue:
    def test_enqueue_drain_priority_order(self) -> None:
        q = EventQueue()
        low = _make_event(topic="low", effects=[EventEffect(type="inject_context", priority="low")])
        normal = _make_event(topic="normal", effects=[EventEffect(type="inject_context", priority="normal")])
        high = _make_event(topic="high", effects=[EventEffect(type="inject_context", priority="high")])
        urgent = _make_event(topic="urgent", effects=[EventEffect(type="inject_context", priority="urgent")])

        # Enqueue in reverse priority order
        q.enqueue(low)
        q.enqueue(normal)
        q.enqueue(high)
        q.enqueue(urgent)

        result = q.drain()
        assert len(result) == 4
        # Should come out in priority order: urgent, high, normal, low
        assert [e.topic for e in result] == ["urgent", "high", "normal", "low"]

    def test_drain_max_count(self) -> None:
        q = EventQueue()
        for _ in range(10):
            q.enqueue(_make_event())
        result = q.drain(max_count=3)
        assert len(result) == 3
        assert len(q) == 7

    def test_drain_max_count_none(self) -> None:
        q = EventQueue()
        for _ in range(5):
            q.enqueue(_make_event())
        result = q.drain(max_count=None)
        assert len(result) == 5
        assert len(q) == 0

    def test_drain_empty_queue(self) -> None:
        q = EventQueue()
        result = q.drain()
        assert result == []

    def test_drain_empty_priority_levels(self) -> None:
        q = EventQueue()
        # Only enqueue at "urgent", leave other levels empty
        urgent = _make_event(topic="only-urgent", effects=[EventEffect(type="inject_context", priority="urgent")])
        q.enqueue(urgent)
        result = q.drain()
        assert len(result) == 1
        assert result[0].topic == "only-urgent"

    def test_len_and_bool(self) -> None:
        q = EventQueue()
        assert len(q) == 0
        assert not q

        q.enqueue(_make_event())
        assert len(q) == 1
        assert q

    def test_priority_from_multiple_effects(self) -> None:
        q = EventQueue()
        event = _make_event(topic="multi-effect", effects=[
            EventEffect(type="inject_context", priority="low"),
            EventEffect(type="notify_user", priority="urgent"),
        ])
        q.enqueue(event)
        # Should be in the urgent queue (highest priority wins)
        result = q.drain()
        assert len(result) == 1
        assert result[0].topic == "multi-effect"

    def test_priority_no_effects(self) -> None:
        q = EventQueue()
        event = _make_event(topic="no-effects", effects=None)
        q.enqueue(event)
        # Should default to "normal"
        assert len(q) == 1
        result = q.drain()
        assert result[0].topic == "no-effects"

    def test_enqueue_drain_is_destructive(self) -> None:
        q = EventQueue()
        q.enqueue(_make_event())
        q.enqueue(_make_event())
        assert len(q) == 2
        q.drain()
        assert len(q) == 0
        assert not q
