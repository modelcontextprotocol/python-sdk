"""Webhook delivery (SEP-3415): subscriptions keyed by who asked, for what, and where to deliver."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import httpx2
from anyio.abc import TaskGroup
from mcp_types import INVALID_PARAMS
from pydantic import BaseModel

from mcp.experimental.events._callbacks import CallbackFailure, Callbacks, NonPublicAddress
from mcp.experimental.events.event_type import EventBatch, EventQuery, EventType, Subscriber
from mcp.experimental.events.signing import decode_secret
from mcp.experimental.events.types import (
    CALLBACK_ENDPOINT_ERROR,
    NOT_FOUND,
    DeliveryError,
    DeliveryStatus,
    SubscribeEventsParams,
    SubscribeEventsResult,
    UnsubscribeEventsParams,
    events_error,
)
from mcp.shared.exceptions import MCPError

__all__ = ["Webhooks"]

logger = logging.getLogger(__name__)

_ROTATION_GRACE = timedelta(minutes=5)


@dataclass
class Webhooks:
    """Configuration for webhook delivery. Passing it to `Events` offers webhook on every event type.

    Subscriptions live in memory, so the server grants finite TTLs only and clients
    resubscribe after a restart. `trusted_origins` (e.g. `"http://127.0.0.1:9000"`) are
    exempt from the `https` and public-address rules, for local receivers in development.
    """

    max_ttl: timedelta = timedelta(hours=1)
    min_ttl: timedelta = timedelta(minutes=1)
    trusted_origins: Collection[str] = ()
    retry_delays: Sequence[timedelta] = (
        timedelta(seconds=5),
        timedelta(seconds=30),
        timedelta(minutes=2),
        timedelta(minutes=5),
    )
    """Waits between attempts to deliver one event; it is abandoned after the last."""
    http_client: httpx2.AsyncClient | None = None
    """Client for the POSTs; by default one with a 5 second timeout, owned by the server."""


@dataclass
class _Subscription:
    id: str
    key: str
    event_type: EventType[Any, Any]
    subscriber: Subscriber[Any]
    url: str
    secret: str
    expires_at: datetime
    cursor: str | None
    scope: anyio.CancelScope = field(default_factory=anyio.CancelScope)
    previous_secret: tuple[str, datetime] | None = None
    last_delivery_at: datetime | None = None
    last_error: DeliveryError | None = None
    failed_since: datetime | None = None

    def signing_secrets(self) -> list[str]:
        if self.previous_secret is not None and self.previous_secret[1] > datetime.now(UTC):
            return [self.secret, self.previous_secret[0]]
        return [self.secret]

    def status(self) -> DeliveryStatus:
        return DeliveryStatus(
            active=True,
            last_delivery_at=self.last_delivery_at,
            last_error=self.last_error,
            failed_since=self.failed_since,
        )


class WebhookSubscriptions:
    """The live webhook subscriptions of one running server, and their delivery loops."""

    def __init__(
        self, config: Webhooks, client: httpx2.AsyncClient, task_group: TaskGroup, poll_interval: timedelta
    ) -> None:
        self._config = config
        self._poll_interval = poll_interval
        self._callbacks = Callbacks(client, config.trusted_origins)
        self._task_group = task_group
        self._subscriptions: dict[str, _Subscription] = {}
        self._verified: set[tuple[str, str]] = set()

    async def subscribe(
        self, event_type: EventType[Any, Any], arguments: BaseModel, principal: str, params: SubscribeEventsParams
    ) -> SubscribeEventsResult:
        url, secret = params.delivery.url, params.delivery.secret
        try:
            self._callbacks.validate(url)
            decode_secret(secret)
        except ValueError as exc:
            raise MCPError(code=INVALID_PARAMS, message=str(exc)) from None
        key = json.dumps([principal, url, event_type.name, params.arguments or {}], sort_keys=True)
        subscription_id = f"sub_{hashlib.sha256(key.encode()).hexdigest()[:16]}"
        ttl = self._grant(params)
        if (existing := self._subscriptions.get(key)) is not None:
            return self._refresh(existing, secret, ttl)
        if (principal, url) not in self._verified:
            try:
                await self._callbacks.verify(url, subscription_id, secret)
            except NonPublicAddress as exc:
                raise MCPError(code=INVALID_PARAMS, message=str(exc)) from None
            except CallbackFailure as exc:
                raise events_error(CALLBACK_ENDPOINT_ERROR, reason=exc.reason) from None
            self._verified.add((principal, url))
        max_age = timedelta(milliseconds=params.max_age_ms) if params.max_age_ms is not None else None
        batch = await event_type.read(EventQuery(arguments, params.cursor, principal, max_age))
        subscriber = Subscriber(id=subscription_id, arguments=arguments, principal=principal, mode="webhook")
        subscription = _Subscription(
            id=subscription_id,
            key=key,
            event_type=event_type,
            subscriber=subscriber,
            url=url,
            secret=secret,
            expires_at=datetime.now(UTC) + ttl,
            # Not yet delivered, so only the supplied cursor is safe to persist; after a gap it is stale.
            cursor=params.cursor if batch.events and not batch.truncated else batch.cursor,
        )
        subscription.scope.deadline = anyio.current_time() + ttl.total_seconds()
        for hook in event_type.subscribe_hooks:
            await hook(subscriber)
        self._subscriptions[key] = subscription
        self._task_group.start_soon(self._run, subscription, batch)
        return SubscribeEventsResult(
            id=subscription_id,
            refresh_before=subscription.expires_at,
            cursor=subscription.cursor,
            truncated=batch.truncated,
        )

    def unsubscribe(self, event_type: EventType[Any, Any], principal: str, params: UnsubscribeEventsParams) -> None:
        key = json.dumps([principal, params.delivery.url, event_type.name, params.arguments or {}], sort_keys=True)
        subscription = self._subscriptions.pop(key, None)
        if subscription is None:
            raise events_error(NOT_FOUND, kind="subscription")
        subscription.scope.cancel()

    def _grant(self, params: SubscribeEventsParams) -> timedelta:
        # In-memory subscriptions cannot honour "no expiry", so an omitted or null ttlMs gets the cap.
        if params.ttl_ms is None:
            return self._config.max_ttl
        return min(max(timedelta(milliseconds=params.ttl_ms), self._config.min_ttl), self._config.max_ttl)

    def _refresh(self, subscription: _Subscription, secret: str, ttl: timedelta) -> SubscribeEventsResult:
        if secret != subscription.secret:
            subscription.previous_secret = (subscription.secret, datetime.now(UTC) + _ROTATION_GRACE)
            subscription.secret = secret
        subscription.expires_at = datetime.now(UTC) + ttl
        subscription.scope.deadline = anyio.current_time() + ttl.total_seconds()
        return SubscribeEventsResult(
            id=subscription.id,
            refresh_before=subscription.expires_at,
            cursor=subscription.cursor,
            delivery_status=subscription.status(),
        )

    async def _run(self, subscription: _Subscription, batch: EventBatch[Any]) -> None:
        event_type, subscriber = subscription.event_type, subscription.subscriber
        try:
            with subscription.scope:
                while True:
                    for index, occurrence in enumerate(batch.events):
                        last = index == len(batch.events) - 1
                        body = event_type.wire(occurrence, batch.cursor if last else subscription.cursor)
                        await self._deliver(subscription, body.model_dump(mode="json", by_alias=True))
                    subscription.cursor = batch.cursor
                    delay = timedelta(0) if batch.has_more else batch.next_poll or self._poll_interval
                    await event_type.buffer.wait(delay.total_seconds())
                    batch = await self._read(subscription)
        finally:
            if self._subscriptions.get(subscription.key) is subscription:
                del self._subscriptions[subscription.key]
        for hook in event_type.unsubscribe_hooks:
            await hook(subscriber)

    async def _read(self, subscription: _Subscription) -> EventBatch[Any]:
        query = EventQuery(subscription.subscriber.arguments, subscription.cursor, subscription.subscriber.principal)
        try:
            batch = await subscription.event_type.read(query)
        except MCPError as exc:
            await self._deliver(subscription, {"type": "terminated", "error": exc.error.model_dump(exclude_none=True)})
            subscription.scope.cancel()
            return EventBatch(cursor=subscription.cursor)
        except Exception:
            # The check function is user code: a crash must not take the server's task group down.
            logger.exception("check function for %r raised", subscription.event_type.name)
            return EventBatch(cursor=subscription.cursor)
        if batch.truncated:
            await self._deliver(subscription, {"type": "gap", "cursor": batch.cursor})
        return batch

    async def _deliver(self, subscription: _Subscription, body: dict[str, Any]) -> None:
        kind = body.get("type", "event")
        message_id = f"msg_{kind}_{secrets.token_hex(12)}" if kind != "event" else f"msg_{secrets.token_hex(16)}"
        for delay in [*self._config.retry_delays, None]:
            try:
                response = await self._callbacks.post(
                    subscription.url, subscription.id, subscription.signing_secrets(), message_id, body
                )
            except NonPublicAddress:
                logger.warning("abandoned a delivery to %s: it resolves to a non-public address", subscription.url)
                subscription.last_error = "connection_refused"
                return
            except CallbackFailure as exc:
                subscription.last_error = exc.reason
            else:
                if response.is_success:
                    subscription.last_delivery_at = datetime.now(UTC)
                    subscription.last_error = subscription.failed_since = None
                    return
                subscription.last_error = "http_5xx" if response.status_code >= 500 else "http_4xx"
                if response.status_code in (410, 413):
                    return
            subscription.failed_since = subscription.failed_since or datetime.now(UTC)
            if delay is not None:
                await anyio.sleep(delay.total_seconds())
