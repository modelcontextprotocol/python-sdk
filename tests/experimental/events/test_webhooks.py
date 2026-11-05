"""Tests for webhook delivery of MCP Events (SEP-3415), server side and the client's `subscribe`.

Deliveries go through an in-process ASGI transport into a real `WebhookReceiver`. Tests about a
failing or hostile endpoint script it with `httpx2.MockTransport` instead, since a well-behaved
receiver cannot produce those responses.
"""

import base64
import json
import socket
import ssl
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import httpx2
import pytest
from inline_snapshot import snapshot
from mcp_types import INVALID_PARAMS
from pydantic import BaseModel

from mcp.client.client import Client
from mcp.experimental.events.client import Events as ClientEvents
from mcp.experimental.events.receiver import Delivery, WebhookGap, WebhookReceiver, WebhookTerminated
from mcp.experimental.events.server import EventBatch, EventQuery, Events, Occurrence, Subscriber, Webhooks
from mcp.experimental.events.types import (
    CALLBACK_ENDPOINT_ERROR,
    FORBIDDEN,
    NOT_FOUND,
    UNSUPPORTED,
    EventOccurrence,
    SubscribeEventsParams,
    SubscribeEventsRequest,
    SubscribeEventsResult,
    UnsubscribeEventsParams,
    UnsubscribeEventsRequest,
    UnsubscribeEventsResult,
    WebhookDelivery,
    WebhookTarget,
    events_error,
)
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError

pytestmark = pytest.mark.anyio

SECRET = "whsec_" + base64.b64encode(b"k" * 32).decode()
ROTATED_SECRET = "whsec_" + base64.b64encode(b"r" * 32).decode()
URL = "https://client.test/hooks"


class ServiceFilter(BaseModel):
    service: str


class Incident(BaseModel):
    service: str
    title: str


class Inbox:
    """Collects deliveries, and lets a test wait until a number of them arrived."""

    def __init__(self) -> None:
        self.deliveries: list[Delivery] = []
        self._arrived = anyio.Event()

    async def __call__(self, delivery: Delivery) -> None:
        self.deliveries.append(delivery)
        self._arrived.set()
        self._arrived = anyio.Event()

    async def wait_for(self, count: int) -> None:
        with anyio.fail_after(5):
            while len(self.deliveries) < count:
                await self._arrived.wait()


def echo_challenge(request: httpx2.Request) -> httpx2.Response:
    """Answer the verification request the way a willing endpoint does."""
    challenge = json.loads(request.content)["challenge"]
    return httpx2.Response(200, json={"challenge": challenge})


def subscribe_request(
    ttl_ms: int | None = None, secret: str = SECRET, url: str = URL, cursor: str | None = None
) -> SubscribeEventsRequest:
    params = SubscribeEventsParams(
        name="incident.created",
        arguments={"service": "billing"},
        delivery=WebhookDelivery(url=url, secret=secret),
        cursor=cursor,
        ttl_ms=ttl_ms,
    )
    return SubscribeEventsRequest(params=params)


async def test_webhook_subscription_delivers_matching_events_until_the_client_leaves() -> None:
    """Events are POSTed, signed, to the verified callback with the subscription's cursor, and leaving
    `subscribe` unsubscribes, ending the subscription (spec-mandated flow).

    Steps:
    1. Subscribe: the server verifies the endpoint, then answers with the subscription id and cursor.
    2. Emit two matching events and one that does not match; the receiver gets the two.
    3. Leave the block: the subscription ends, firing `on_unsubscribe`.
    """
    inbox = Inbox()
    hooks: list[tuple[str, Subscriber[ServiceFilter]]] = []
    ended = anyio.Event()
    events = Events(
        webhooks=Webhooks(
            http_client=httpx2.AsyncClient(transport=httpx2.ASGITransport(app=WebhookReceiver(SECRET, inbox))),
            trusted_origins=["https://client.test"],
        ),
        principal=lambda ctx: "alice",
    )
    incidents = events.event("incident.created", arguments=ServiceFilter, payload=Incident)

    @incidents.match
    def same_service(arguments: ServiceFilter, incident: Incident) -> bool:
        return arguments.service == incident.service

    @incidents.on_subscribe
    async def subscribed(subscriber: Subscriber[ServiceFilter]) -> None:
        hooks.append(("subscribe", subscriber))

    @incidents.on_unsubscribe
    async def unsubscribed(subscriber: Subscriber[ServiceFilter]) -> None:
        hooks.append(("unsubscribe", subscriber))
        ended.set()

    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp, extensions=[ClientEvents()]) as client:
        events_client = client.extension(ClientEvents)
        async with events_client.subscribe("incident.created", {"service": "billing"}, url=URL, secret=SECRET) as sub:
            incidents.emit(Occurrence(Incident(service="billing", title="a"), id="inc-1"))
            incidents.emit(Incident(service="search", title="not ours"))
            incidents.emit(Occurrence(Incident(service="billing", title="b"), id="inc-2"))
            await inbox.wait_for(2)
        with anyio.fail_after(5):
            await ended.wait()

    first, second = inbox.deliveries
    assert isinstance(first, EventOccurrence) and isinstance(second, EventOccurrence)
    assert [(first.event_id, first.data), (second.event_id, second.data)] == [
        ("inc-1", {"service": "billing", "title": "a"}),
        ("inc-2", {"service": "billing", "title": "b"}),
    ]
    assert first.cursor == sub.cursor
    assert second.cursor is not None and second.cursor != sub.cursor
    [(_, subscriber), (_, same)] = hooks
    assert subscriber is same
    assert (subscriber.id, subscriber.principal, subscriber.mode) == (sub.id, "alice", "webhook")


async def test_resubscribing_refreshes_the_subscription_and_signs_with_both_secrets_during_rotation() -> None:
    """Subscribing again with the same key refreshes the same subscription and reports its delivery
    status; after a secret change, deliveries carry both signatures for a grace period (spec-mandated)."""
    inbox = Inbox()
    events = Events(
        webhooks=Webhooks(
            http_client=httpx2.AsyncClient(transport=httpx2.ASGITransport(app=WebhookReceiver(SECRET, inbox))),
            trusted_origins=["https://client.test"],
        ),
        principal=lambda ctx: "alice",
    )
    incidents = events.event("incident.created", arguments=ServiceFilter, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp) as client:
        created = await client.session.send_request(subscribe_request(), SubscribeEventsResult)
        refreshed = await client.session.send_request(subscribe_request(secret=ROTATED_SECRET), SubscribeEventsResult)
        incidents.emit(Incident(service="billing", title="a"))
        await inbox.wait_for(1)
        again = await client.session.send_request(subscribe_request(secret=ROTATED_SECRET), SubscribeEventsResult)
        assert refreshed.id == created.id
        assert created.delivery_status is None
        assert refreshed.delivery_status is not None
        assert refreshed.delivery_status.model_dump(exclude_none=True) == snapshot({"active": True})
        assert again.delivery_status is not None and again.delivery_status.last_delivery_at is not None


async def test_unsubscribing_an_unknown_subscription_raises_not_found() -> None:
    """`events/unsubscribe` for a key with no subscription is `NotFound` (spec-mandated)."""
    events = Events(webhooks=Webhooks(), principal=lambda ctx: "alice")
    events.event("incident.created", arguments=ServiceFilter, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])
    params = UnsubscribeEventsParams(
        name="incident.created", arguments={"service": "billing"}, delivery=WebhookTarget(url=URL)
    )

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(UnsubscribeEventsRequest(params=params), UnsubscribeEventsResult)

    assert exc_info.value.code == NOT_FOUND


async def test_a_verified_callback_is_verified_again_only_after_its_last_subscription_ends() -> None:
    """Verification is per principal and callback URL, so another subscription to the same endpoint
    skips the challenge, and the cache lives only as long as those subscriptions (spec-mandated
    scope of verification)."""
    challenges: list[str] = []

    async def endpoint(request: httpx2.Request) -> httpx2.Response:
        challenges.append(json.loads(request.content)["challenge"])
        return echo_challenge(request)

    events = Events(
        webhooks=Webhooks(
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(endpoint)),
            trusted_origins=["https://client.test"],
        ),
        principal=lambda ctx: "alice",
    )
    events.event("incident.created", arguments=ServiceFilter, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])
    search = subscribe_request()
    search.params.arguments = {"service": "search"}

    async with Client(mcp) as client:
        billing_sub = await client.session.send_request(subscribe_request(), SubscribeEventsResult)
        search_sub = await client.session.send_request(search, SubscribeEventsResult)
        assert billing_sub.id != search_sub.id
        assert len(challenges) == 1

        for request in (subscribe_request(), search):
            unsubscribe = UnsubscribeEventsParams(
                name="incident.created", arguments=request.params.arguments, delivery=WebhookTarget(url=URL)
            )
            await client.session.send_request(UnsubscribeEventsRequest(params=unsubscribe), UnsubscribeEventsResult)
        await anyio.wait_all_tasks_blocked()
        await client.session.send_request(subscribe_request(), SubscribeEventsResult)
        assert len(challenges) == 2


async def test_concurrent_identical_subscribes_upsert_one_subscription() -> None:
    """Two `events/subscribe` calls for one key that race each other create a single subscription:
    one verification and one `on_subscribe` (spec-mandated idempotent upsert)."""
    challenges: list[str] = []
    subscribed: list[str] = []

    async def endpoint(request: httpx2.Request) -> httpx2.Response:
        challenges.append(json.loads(request.content)["challenge"])
        await anyio.wait_all_tasks_blocked()
        return echo_challenge(request)

    events = Events(
        webhooks=Webhooks(
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(endpoint)),
            trusted_origins=["https://client.test"],
        ),
        principal=lambda ctx: "alice",
    )
    incidents = events.event("incident.created", arguments=ServiceFilter, payload=Incident)

    @incidents.on_subscribe
    async def on_subscribe(subscriber: Subscriber[ServiceFilter]) -> None:
        subscribed.append(subscriber.id)

    mcp = MCPServer("pager", extensions=[events])
    results: list[SubscribeEventsResult] = []

    async with Client(mcp) as client:

        async def subscribe() -> None:
            results.append(await client.session.send_request(subscribe_request(), SubscribeEventsResult))

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(subscribe)
            task_group.start_soon(subscribe)

        assert len(challenges) == 1
        assert len(subscribed) == 1
        assert results[0].id == results[1].id


async def test_an_on_subscribe_hook_that_raises_rejects_the_subscription() -> None:
    """`on_subscribe` is where the server checks the principal's access: raising `Forbidden` fails
    `events/subscribe` and leaves no subscription behind (spec-mandated subscribe-time authorization)."""
    events = Events(
        webhooks=Webhooks(
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(echo_challenge)),
            trusted_origins=["https://client.test"],
        ),
        principal=lambda ctx: "mallory",
    )
    incidents = events.event("incident.created", arguments=ServiceFilter, payload=Incident)

    @incidents.on_subscribe
    async def check_access(subscriber: Subscriber[ServiceFilter]) -> None:
        raise events_error(FORBIDDEN, reason=f"{subscriber.principal} cannot see {subscriber.arguments.service}")

    mcp = MCPServer("pager", extensions=[events])
    unsubscribe = UnsubscribeEventsParams(
        name="incident.created", arguments={"service": "billing"}, delivery=WebhookTarget(url=URL)
    )

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as rejected:
            await client.session.send_request(subscribe_request(), SubscribeEventsResult)
        with pytest.raises(MCPError) as missing:
            await client.session.send_request(UnsubscribeEventsRequest(params=unsubscribe), UnsubscribeEventsResult)
        assert rejected.value.error.model_dump(exclude_none=True) == snapshot(
            {"code": -32024, "message": "Forbidden", "data": {"reason": "mallory cannot see billing"}}
        )
        assert missing.value.code == NOT_FOUND


async def test_subscribe_keeps_the_supplied_cursor_until_the_first_batch_is_delivered() -> None:
    """The subscribe response's cursor must be safe to persist, so while the first batch is still
    undelivered it stays the client's own, even when the batch also reports a gap (spec-mandated
    watermark)."""
    inbox = Inbox()
    answers = [
        EventBatch(cursor="c9", events=[Occurrence(Incident(service="billing", title="a"), id="e1")], truncated=True)
    ]
    events = Events(
        webhooks=Webhooks(
            http_client=httpx2.AsyncClient(transport=httpx2.ASGITransport(app=WebhookReceiver(SECRET, inbox))),
            trusted_origins=["https://client.test"],
        ),
        principal=lambda ctx: "alice",
    )
    incidents = events.event("incident.created", arguments=ServiceFilter, payload=Incident)

    @incidents.check
    async def check(query: EventQuery[ServiceFilter]) -> EventBatch[Incident]:
        return answers.pop() if answers else EventBatch(cursor="c9")

    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp) as client:
        result = await client.session.send_request(subscribe_request(cursor="c1"), SubscribeEventsResult)
        await inbox.wait_for(1)
        assert (result.cursor, result.truncated) == ("c1", True)
        [event] = inbox.deliveries
        assert isinstance(event, EventOccurrence) and event.cursor == "c9"


async def test_webhook_calls_without_an_authenticated_principal_raise_forbidden() -> None:
    """Webhook subscriptions are keyed by principal, so unauthenticated callers are refused (spec-mandated)."""
    events = Events(webhooks=Webhooks())
    events.event("incident.created", arguments=ServiceFilter, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])
    unsubscribe = UnsubscribeEventsParams(
        name="incident.created", arguments={"service": "billing"}, delivery=WebhookTarget(url=URL)
    )

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as subscribe_error:
            await client.session.send_request(subscribe_request(), SubscribeEventsResult)
        with pytest.raises(MCPError) as unsubscribe_error:
            request = UnsubscribeEventsRequest(params=unsubscribe)
            await client.session.send_request(request, UnsubscribeEventsResult)

    assert subscribe_error.value.code == FORBIDDEN
    assert unsubscribe_error.value.code == FORBIDDEN


async def test_webhook_subscriptions_belong_to_the_access_token_principal_by_default() -> None:
    """Without a `principal` resolver, the caller's OAuth client, issuer, and subject identify it (SDK-defined)."""
    subscribers: list[Subscriber[ServiceFilter]] = []
    events = Events(
        webhooks=Webhooks(
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(echo_challenge)),
            trusted_origins=["https://client.test"],
        )
    )
    incidents = events.event("incident.created", arguments=ServiceFilter, payload=Incident)

    @incidents.on_subscribe
    async def subscribed(subscriber: Subscriber[ServiceFilter]) -> None:
        subscribers.append(subscriber)

    mcp = MCPServer("pager", extensions=[events])
    token = AccessToken(token="t", client_id="app", scopes=[], subject="alice", claims={"iss": "https://idp.test"})
    reset = auth_context_var.set(AuthenticatedUser(token))
    try:
        async with Client(mcp) as client:
            await client.session.send_request(subscribe_request(), SubscribeEventsResult)
            assert [s.principal for s in subscribers] == ['["app","https://idp.test","alice"]']
    finally:
        auth_context_var.reset(reset)  # pragma: lax no cover  - python/cpython#106749: 3.11 drops this line event


async def test_subscribe_with_a_delivery_mode_other_than_webhook_raises_unsupported() -> None:
    """`events/subscribe` only serves webhook delivery (spec-mandated `Unsupported`)."""
    events = Events(webhooks=Webhooks(), principal=lambda ctx: "alice")
    events.event("incident.created", arguments=ServiceFilter, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])
    request = subscribe_request()
    request.params.delivery.mode = "carrier-pigeon"

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(request, SubscribeEventsResult)

    assert exc_info.value.code == UNSUPPORTED
    assert exc_info.value.data == {"feature": "deliveryMode", "value": "carrier-pigeon"}


@pytest.mark.parametrize(
    ("url", "secret"),
    [
        pytest.param("http://client.test/hooks", SECRET, id="plain-http"),
        pytest.param("/hooks", SECRET, id="relative-url"),
        pytest.param("https://localhost/hooks", SECRET, id="loopback-host"),
        pytest.param(URL, "not-a-whsec-secret", id="secret-prefix"),
        pytest.param(URL, "whsec_!!!", id="secret-not-base64"),
        pytest.param(URL, "whsec_" + base64.b64encode(b"short").decode(), id="secret-too-short"),
    ],
)
async def test_subscribe_with_an_unsafe_callback_or_malformed_secret_raises_invalid_params(
    url: str, secret: str
) -> None:
    """Callback URLs must be https and publicly routable, and secrets `whsec_` base64 of 24-64 bytes
    (spec-mandated SSRF rules and Standard Webhooks format)."""
    events = Events(
        webhooks=Webhooks(http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(echo_challenge))),
        principal=lambda ctx: "alice",
    )
    events.event("incident.created", arguments=ServiceFilter, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(subscribe_request(url=url, secret=secret), SubscribeEventsResult)

    assert exc_info.value.code == INVALID_PARAMS


_TLS_FAILURE = httpx2.ConnectError("certificate verify failed")
_TLS_FAILURE.__cause__ = ssl.SSLError("bad certificate")


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        pytest.param(httpx2.Response(503), "http_5xx", id="5xx"),
        pytest.param(httpx2.Response(404), "http_4xx", id="4xx"),
        pytest.param(httpx2.Response(200, json={"challenge": "guessed"}), "challenge_failed", id="wrong-challenge"),
        pytest.param(httpx2.Response(200, text="ok"), "challenge_failed", id="not-json"),
        pytest.param(httpx2.Response(200, json=["ok"]), "challenge_failed", id="json-without-challenge"),
        pytest.param(httpx2.ConnectError("connection refused"), "connection_refused", id="refused"),
        pytest.param(_TLS_FAILURE, "tls_error", id="tls"),
        pytest.param(httpx2.ReadTimeout("timed out"), "timeout", id="timeout"),
    ],
)
async def test_subscribe_to_an_endpoint_that_fails_verification_raises_callback_endpoint_error(
    outcome: httpx2.Response | Exception, reason: str
) -> None:
    """A callback that does not echo the verification challenge is refused with a categorized reason,
    never the endpoint's own response (spec-mandated)."""

    async def endpoint(request: httpx2.Request) -> httpx2.Response:
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    events = Events(
        webhooks=Webhooks(
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(endpoint)),
            trusted_origins=["https://client.test"],
        ),
        principal=lambda ctx: "alice",
    )
    events.event("incident.created", arguments=ServiceFilter, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(subscribe_request(), SubscribeEventsResult)

    assert exc_info.value.code == CALLBACK_ENDPOINT_ERROR
    assert exc_info.value.data == {"reason": reason}


@pytest.mark.parametrize(
    ("family", "address"),
    [
        pytest.param(socket.AF_INET, "93.184.215.14", id="ipv4"),
        pytest.param(socket.AF_INET6, "2606:2800:21f:cb07:6820:80da:af6b:8b2c", id="ipv6"),
    ],
)
async def test_callbacks_connect_to_the_checked_public_address_with_the_original_host(
    monkeypatch: pytest.MonkeyPatch, family: socket.AddressFamily, address: str
) -> None:
    """The server connects to the address it validated, keeping `Host` and TLS SNI, so a DNS
    answer cannot change between the check and the connection (spec-mandated SSRF rule)."""
    seen: list[httpx2.Request] = []

    async def resolve(host: str, port: int, **kwargs: Any) -> list[Any]:
        assert (host, port) == ("hooks.example.com", 443)
        return [(family, socket.SOCK_STREAM, 6, "", (address, port))]

    async def endpoint(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return echo_challenge(request)

    monkeypatch.setattr(anyio, "getaddrinfo", resolve)
    events = Events(
        webhooks=Webhooks(http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(endpoint))),
        principal=lambda ctx: "alice",
    )
    events.event("incident.created", arguments=ServiceFilter, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp) as client:
        await client.session.send_request(subscribe_request(url="https://hooks.example.com/mcp"), SubscribeEventsResult)
        [verification] = seen
        assert (verification.url.host, verification.url.path) == (address, "/mcp")
        assert verification.headers["host"] == "hooks.example.com"
        assert verification.extensions["sni_hostname"] == "hooks.example.com"


async def test_subscribe_to_a_host_that_does_not_resolve_raises_callback_endpoint_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unresolvable callback host is reported as `connection_refused` (spec-mandated categories)."""

    async def resolve(host: str, port: int, **kwargs: Any) -> list[Any]:
        raise socket.gaierror("no such host")

    monkeypatch.setattr(anyio, "getaddrinfo", resolve)
    events = Events(webhooks=Webhooks(), principal=lambda ctx: "alice")
    events.event("incident.created", arguments=ServiceFilter, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(subscribe_request(url="https://nowhere.test/"), SubscribeEventsResult)

    assert exc_info.value.data == {"reason": "connection_refused"}


async def test_a_callback_host_that_rebinds_to_a_private_address_gets_no_deliveries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Addresses are checked again on every delivery, so a host that passed verification and then
    resolves to a private address is not contacted (spec-mandated delivery-time SSRF check)."""
    answers = ["93.184.215.14", "127.0.0.1"]
    rebound = anyio.Event()
    posted: list[httpx2.Request] = []

    async def resolve(host: str, port: int, **kwargs: Any) -> list[Any]:
        address = answers.pop(0)
        if not answers:
            rebound.set()
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    async def endpoint(request: httpx2.Request) -> httpx2.Response:
        posted.append(request)
        return echo_challenge(request)

    monkeypatch.setattr(anyio, "getaddrinfo", resolve)
    events = Events(
        webhooks=Webhooks(http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(endpoint))),
        principal=lambda ctx: "alice",
    )
    incidents = events.event("incident.created", arguments=ServiceFilter, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])
    request = subscribe_request(url="https://hooks.example.com/mcp")

    async with Client(mcp) as client:
        await client.session.send_request(request, SubscribeEventsResult)
        incidents.emit(Incident(service="billing", title="a"))
        with anyio.fail_after(5):
            await rebound.wait()
        refreshed = await client.session.send_request(request, SubscribeEventsResult)
        assert len(posted) == 1
        assert refreshed.delivery_status is not None
        assert refreshed.delivery_status.last_error == "connection_refused"


async def test_failed_deliveries_are_retried_then_abandoned_and_reported_on_refresh() -> None:
    """A delivery is retried with the same `webhook-id`, abandoned after the last retry, and the
    failure shows in `deliveryStatus` until a later delivery succeeds (spec-mandated)."""
    attempts: list[tuple[str, str]] = []
    third_attempt = anyio.Event()
    release = anyio.Event()

    async def endpoint(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        if body.get("type") == "verification":
            return echo_challenge(request)
        attempts.append((request.headers["webhook-id"], body["data"]["title"]))
        if len(attempts) == 1:
            raise httpx2.ConnectError("connection refused")
        if len(attempts) == 2:
            return httpx2.Response(503)
        third_attempt.set()
        await release.wait()
        return httpx2.Response(204)

    webhooks = Webhooks(
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(endpoint)),
        trusted_origins=["https://client.test"],
        retry_delays=[timedelta(0)],
    )
    events = Events(webhooks=webhooks, principal=lambda ctx: "alice")
    incidents = events.event("incident.created", arguments=ServiceFilter, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp) as client:
        await client.session.send_request(subscribe_request(), SubscribeEventsResult)
        incidents.emit(Incident(service="billing", title="lost"))
        incidents.emit(Incident(service="billing", title="kept"))
        with anyio.fail_after(5):
            await third_attempt.wait()
        failing = await client.session.send_request(subscribe_request(), SubscribeEventsResult)
        release.set()
        assert [title for _, title in attempts] == ["lost", "lost", "kept"]
        assert attempts[0][0] == attempts[1][0] != attempts[2][0]
        assert failing.delivery_status is not None
        assert failing.delivery_status.last_error == "http_5xx"
        assert failing.delivery_status.failed_since is not None


async def test_a_gone_response_abandons_the_delivery_without_retrying() -> None:
    """`410 Gone` from the callback stops retries for that delivery (SDK-defined, after Standard Webhooks)."""
    titles: list[str] = []
    second = anyio.Event()

    async def endpoint(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        if body.get("type") == "verification":
            return echo_challenge(request)
        titles.append(body["data"]["title"])
        if len(titles) == 2:
            second.set()
        return httpx2.Response(410 if len(titles) == 1 else 204)

    webhooks = Webhooks(
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(endpoint)),
        trusted_origins=["https://client.test"],
        retry_delays=[timedelta(0)],
    )
    events = Events(webhooks=webhooks, principal=lambda ctx: "alice")
    incidents = events.event("incident.created", arguments=ServiceFilter, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp) as client:
        await client.session.send_request(subscribe_request(), SubscribeEventsResult)
        incidents.emit(Incident(service="billing", title="gone"))
        incidents.emit(Incident(service="billing", title="next"))
        with anyio.fail_after(5):
            await second.wait()
        assert titles == ["gone", "next"]


async def test_requested_ttls_are_clamped_to_the_servers_bounds() -> None:
    """The server grants the suggested `ttlMs` within `min_ttl`..`max_ttl` and answers with
    `refreshBefore` (spec-mandated TTL negotiation; this tests a time-based feature)."""
    webhooks = Webhooks(
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(echo_challenge)),
        trusted_origins=["https://client.test"],
        min_ttl=timedelta(hours=1),
        max_ttl=timedelta(hours=2),
    )
    events = Events(webhooks=webhooks, principal=lambda ctx: "alice")
    events.event("incident.created", arguments=ServiceFilter, payload=Incident)
    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp) as client:
        before = datetime.now(UTC)
        short = await client.session.send_request(subscribe_request(ttl_ms=1), SubscribeEventsResult)
        long = await client.session.send_request(subscribe_request(ttl_ms=10**9), SubscribeEventsResult)
        assert short.refresh_before is not None and long.refresh_before is not None
        assert timedelta(minutes=59) < short.refresh_before - before <= timedelta(hours=1, minutes=1)
        assert timedelta(hours=1, minutes=59) < long.refresh_before - before <= timedelta(hours=2, minutes=1)


async def test_a_subscription_that_is_not_refreshed_ends_when_its_ttl_lapses() -> None:
    """An unrefreshed subscription expires, firing `on_unsubscribe` (spec-mandated; a time-based feature,
    so the test waits for a 50 ms TTL to really lapse)."""
    lapsed = anyio.Event()
    webhooks = Webhooks(
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(echo_challenge)),
        trusted_origins=["https://client.test"],
        min_ttl=timedelta(0),
    )
    events = Events(webhooks=webhooks, principal=lambda ctx: "alice")
    incidents = events.event("incident.created", arguments=ServiceFilter, payload=Incident)

    @incidents.on_unsubscribe
    async def unsubscribed(subscriber: Subscriber[ServiceFilter]) -> None:
        lapsed.set()

    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp) as client:
        await client.session.send_request(subscribe_request(ttl_ms=50), SubscribeEventsResult)
        with anyio.fail_after(5):
            await lapsed.wait()


async def test_check_function_subscriptions_deliver_gaps_survive_crashes_and_end_on_errors() -> None:
    """A webhook loop over a check function drains `hasMore` batches, POSTs a gap for `truncated`,
    logs and retries a crashing read, and terminates the subscription on an `MCPError` (spec-mandated
    control messages; SDK-defined crash handling).

    Steps:
    1. Subscribe: the first read gives the starting cursor.
    2. The loop reads one event with `has_more`, then crashes, then reads a truncated batch, then fails.
    3. The receiver gets the event, a gap, and a terminated message; `on_unsubscribe` fires.
    """
    inbox = Inbox()
    ended = anyio.Event()
    reads: list[str | None] = []
    answers: list[EventBatch[Incident] | Exception] = [
        EventBatch(cursor="c0"),
        EventBatch(cursor="c1", events=[Occurrence(Incident(service="billing", title="a"), id="e1")], has_more=True),
        RuntimeError("upstream crashed"),
        EventBatch(cursor="c3", truncated=True),
        MCPError(code=FORBIDDEN, message="Forbidden", data={"reason": "access revoked"}),
    ]
    events = Events(
        webhooks=Webhooks(
            http_client=httpx2.AsyncClient(transport=httpx2.ASGITransport(app=WebhookReceiver(SECRET, inbox))),
            trusted_origins=["https://client.test"],
        ),
        principal=lambda ctx: "alice",
        poll_interval=timedelta(0),
    )
    incidents = events.event("incident.created", arguments=ServiceFilter, payload=Incident)

    @incidents.check
    async def check(query: EventQuery[ServiceFilter]) -> EventBatch[Incident]:
        reads.append(query.cursor)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    @incidents.on_unsubscribe
    async def unsubscribed(subscriber: Subscriber[ServiceFilter]) -> None:
        ended.set()

    mcp = MCPServer("pager", extensions=[events])

    async with Client(mcp) as client:
        await client.session.send_request(subscribe_request(), SubscribeEventsResult)
        with anyio.fail_after(5):
            await ended.wait()

    assert reads == [None, "c0", "c1", "c1", "c3"]
    event, gap, terminated = inbox.deliveries
    assert isinstance(event, EventOccurrence) and event.event_id == "e1"
    assert isinstance(gap, WebhookGap) and gap.cursor == "c3"
    assert isinstance(terminated, WebhookTerminated)
    assert terminated.error == {"code": FORBIDDEN, "message": "Forbidden", "data": {"reason": "access revoked"}}
