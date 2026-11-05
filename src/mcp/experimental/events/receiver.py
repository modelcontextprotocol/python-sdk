"""Receive SEP-3415 webhook deliveries: an ASGI app that verifies, decodes, and hands them over.

```python
async def handle(delivery: EventOccurrence | WebhookGap | WebhookTerminated) -> None:
    ...

receiver = WebhookReceiver(secret, handle)
app = Starlette(routes=[Mount("/hooks/events", receiver)])
```
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import Receive, Scope, Send

from mcp.experimental.events.signing import verify
from mcp.experimental.events.types import EventOccurrence

__all__ = ["WebhookGap", "WebhookReceiver", "WebhookTerminated"]


@dataclass(frozen=True)
class WebhookGap:
    """Events were skipped; resume from `cursor`, and reconcile if the gap matters."""

    subscription_id: str
    cursor: str | None


@dataclass(frozen=True)
class WebhookTerminated:
    """The server ended the subscription, e.g. after access was revoked; resubscribing may fail the same way."""

    subscription_id: str
    error: dict[str, Any]


Delivery = EventOccurrence | WebhookGap | WebhookTerminated


class WebhookReceiver:
    """ASGI app for the callback URL of webhook subscriptions made with one `secret`.

    Requests that are unsigned, signed with another secret, or older than `tolerance`
    get a 401 and never reach `handler`. Events are deduplicated on their subscription and
    `event_id` across the last `dedupe_window` events, since servers retry deliveries.
    """

    def __init__(
        self,
        secret: str,
        handler: Callable[[Delivery], Awaitable[None]],
        *,
        tolerance: timedelta = timedelta(minutes=5),
        dedupe_window: int = 1000,
    ) -> None:
        self._secret = secret
        self._handler = handler
        self._tolerance = tolerance
        self._dedupe_window = dedupe_window
        self._seen: OrderedDict[tuple[str, str], None] = OrderedDict()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        response = await self._handle(request) if request.method == "POST" else Response(status_code=405)
        await response(scope, receive, send)

    async def _handle(self, request: Request) -> Response:
        body = await request.body()
        message_id = request.headers.get("webhook-id", "")
        timestamp = request.headers.get("webhook-timestamp", "")
        signature = request.headers.get("webhook-signature", "")
        if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > self._tolerance.total_seconds():
            return Response(status_code=401)
        if not verify(self._secret, message_id, int(timestamp), body, signature):
            return Response(status_code=401)
        subscription_id = request.headers.get("x-mcp-subscription-id", "")
        delivery: Delivery
        try:
            payload = json.loads(body)
            match payload.get("type"):
                case "verification":
                    return JSONResponse({"challenge": str(payload["challenge"])})
                case "gap":
                    delivery = WebhookGap(subscription_id, payload.get("cursor"))
                case "terminated":
                    delivery = WebhookTerminated(subscription_id, dict(payload["error"]))
                case _:
                    delivery = EventOccurrence.model_validate(payload)
        except (ValueError, TypeError, KeyError, AttributeError, ValidationError):
            return Response(status_code=400)
        # One upstream event can match several subscriptions, and each must receive it.
        seen_key = (subscription_id, delivery.event_id) if isinstance(delivery, EventOccurrence) else None
        if seen_key in self._seen:
            return Response(status_code=204)
        await self._handler(delivery)
        if seen_key is not None:
            self._seen[seen_key] = None
            if len(self._seen) > self._dedupe_window:
                self._seen.popitem(last=False)
        return Response(status_code=204)
