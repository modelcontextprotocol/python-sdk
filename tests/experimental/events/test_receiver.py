"""Tests for `WebhookReceiver`, the ASGI app that receives SEP-3415 webhook deliveries.

These drive it with raw HTTP: status codes and signature headers are the behaviour under test.
"""

import base64
import json
import time
from typing import Any

import httpx2
import pytest

from mcp.experimental.events.receiver import Delivery, WebhookGap, WebhookReceiver, WebhookTerminated
from mcp.experimental.events.signing import sign
from mcp.experimental.events.types import EventOccurrence

pytestmark = pytest.mark.anyio

SECRET = "whsec_" + base64.b64encode(b"k" * 32).decode()
EVENT = {"eventId": "e1", "name": "ping", "timestamp": "2026-11-05T12:00:00Z", "data": {"n": 1}, "cursor": "c1"}


def signed(
    body: dict[str, Any] | bytes,
    *,
    secret: str = SECRET,
    timestamp: int | None = None,
    subscription_id: str = "sub_1",
) -> dict[str, Any]:
    content = body if isinstance(body, bytes) else json.dumps(body).encode()
    timestamp = int(time.time()) if timestamp is None else timestamp
    headers = {
        "webhook-id": "msg_1",
        "webhook-timestamp": str(timestamp),
        "webhook-signature": f"v1,{sign(secret, 'msg_1', timestamp, content)}",
        "x-mcp-subscription-id": subscription_id,
    }
    return {"content": content, "headers": headers}


def receiver_client(received: list[Delivery], **kwargs: Any) -> httpx2.AsyncClient:
    async def handle(delivery: Delivery) -> None:
        received.append(delivery)

    app = WebhookReceiver(SECRET, handle, **kwargs)
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="https://client.test")


async def test_receiver_echoes_the_verification_challenge() -> None:
    """A signed verification request is answered with its challenge, proving the endpoint opted in (spec-mandated)."""
    received: list[Delivery] = []
    async with receiver_client(received) as http:
        response = await http.post("/", **signed({"type": "verification", "challenge": "abc"}))

    assert (response.status_code, response.json()) == (200, {"challenge": "abc"})
    assert received == []


async def test_receiver_hands_over_events_gaps_and_terminations() -> None:
    """Each delivery body becomes a typed value for the handler (spec-mandated body shapes)."""
    received: list[Delivery] = []
    async with receiver_client(received) as http:
        statuses = [
            (await http.post("/", **signed(body))).status_code
            for body in (
                EVENT,
                {"type": "gap", "cursor": "c9"},
                {"type": "terminated", "error": {"code": -32024, "message": "Forbidden"}},
            )
        ]

    assert statuses == [204, 204, 204]
    assert received == [
        EventOccurrence.model_validate(EVENT),
        WebhookGap(subscription_id="sub_1", cursor="c9"),
        WebhookTerminated(subscription_id="sub_1", error={"code": -32024, "message": "Forbidden"}),
    ]


async def test_receiver_hands_over_a_retried_event_once_per_subscription_within_the_dedupe_window() -> None:
    """Servers deliver at least once, so an `eventId` repeated on one subscription is acknowledged
    without reaching the handler until it falls out of the window, while the same `eventId` on
    another subscription is a separate delivery (spec-mandated subscription-scoped deduplication)."""
    received: list[Delivery] = []
    async with receiver_client(received, dedupe_window=2) as http:
        for subscription_id, event_id in (
            ("sub_1", "e1"),
            ("sub_1", "e1"),
            ("sub_2", "e1"),
            ("sub_1", "e2"),
            ("sub_1", "e1"),
        ):
            response = await http.post("/", **signed({**EVENT, "eventId": event_id}, subscription_id=subscription_id))
            assert response.status_code == 204

    assert [d.event_id for d in received if isinstance(d, EventOccurrence)] == ["e1", "e1", "e2", "e1"]


@pytest.mark.parametrize(
    "request_kwargs",
    [
        pytest.param(signed(EVENT, secret="whsec_" + base64.b64encode(b"x" * 32).decode()), id="other-secret"),
        pytest.param(signed(EVENT, timestamp=int(time.time()) - 3600), id="stale"),
        pytest.param(
            {**signed(EVENT), "headers": {**signed(EVENT)["headers"], "webhook-timestamp": "soon"}}, id="bad-timestamp"
        ),
        pytest.param(
            {**signed(EVENT), "headers": {**signed(EVENT)["headers"], "webhook-signature": "v2,abc"}},
            id="unknown-version",
        ),
        pytest.param({"content": json.dumps(EVENT).encode()}, id="unsigned"),
    ],
)
async def test_receiver_rejects_unauthenticated_requests_with_401(request_kwargs: dict[str, Any]) -> None:
    """Only bodies signed with the subscription's secret within the tolerance reach the handler
    (spec-mandated Standard Webhooks verification)."""
    received: list[Delivery] = []
    async with receiver_client(received) as http:
        response = await http.post("/", **request_kwargs)

    assert response.status_code == 401
    assert received == []


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"not json", id="not-json"),
        pytest.param({"eventId": "e1"}, id="incomplete-event"),
        pytest.param({"type": "terminated"}, id="terminated-without-error"),
    ],
)
async def test_receiver_rejects_malformed_bodies_with_400(body: dict[str, Any] | bytes) -> None:
    """A signed body that is not a delivery is refused (SDK-defined)."""
    received: list[Delivery] = []
    async with receiver_client(received) as http:
        response = await http.post("/", **signed(body))

    assert response.status_code == 400
    assert received == []


async def test_receiver_only_accepts_post() -> None:
    """Deliveries are POSTs; anything else is `405` (SDK-defined)."""
    async with receiver_client([]) as http:
        response = await http.get("/")

    assert response.status_code == 405
