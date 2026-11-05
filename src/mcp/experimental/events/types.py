"""Wire types and error codes for MCP Events (SEP-3415), shared by the server and client sides."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from mcp_types import PaginatedRequestParams, PaginatedResult, Request, RequestParams, Result
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from mcp.shared.exceptions import MCPError

__all__ = [
    "EXTENSION_ID",
    "NOT_FOUND",
    "FORBIDDEN",
    "RESOURCE_EXHAUSTED",
    "UNSUPPORTED",
    "CALLBACK_ENDPOINT_ERROR",
    "DeliveryMode",
    "DeliveryError",
    "EventDescriptor",
    "EventOccurrence",
    "ListEventsParams",
    "ListEventsResult",
    "ListEventsRequest",
    "PollEventsParams",
    "PollEventsResult",
    "PollEventsRequest",
    "WebhookDelivery",
    "WebhookTarget",
    "DeliveryStatus",
    "SubscribeEventsParams",
    "SubscribeEventsResult",
    "SubscribeEventsRequest",
    "UnsubscribeEventsParams",
    "UnsubscribeEventsResult",
    "UnsubscribeEventsRequest",
    "events_error",
]

EXTENSION_ID = "io.modelcontextprotocol/events"

# Provisional until SEP-3415 is accepted.
NOT_FOUND = -32023
FORBIDDEN = -32024
RESOURCE_EXHAUSTED = -32025
UNSUPPORTED = -32026
CALLBACK_ENDPOINT_ERROR = -32027

_ERROR_MESSAGES = {
    NOT_FOUND: "Not found",
    FORBIDDEN: "Forbidden",
    RESOURCE_EXHAUSTED: "Resource exhausted",
    UNSUPPORTED: "Unsupported",
    CALLBACK_ENDPOINT_ERROR: "Callback endpoint error",
}

DeliveryMode = Literal["poll", "push", "webhook"]

DeliveryError = Literal["connection_refused", "timeout", "tls_error", "http_4xx", "http_5xx", "challenge_failed"]
"""The categories a server reports for a failing callback; never raw endpoint responses."""


def events_error(code: int, **data: Any) -> MCPError:
    """Build one of the SEP-3415 errors, with `data` as its typed payload."""
    return MCPError(code=code, message=_ERROR_MESSAGES[code], data=data or None)


class _Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class EventDescriptor(_Model):
    """One event type, as listed by `events/list`."""

    name: str
    description: str | None = None
    delivery: list[DeliveryMode]
    input_schema: dict[str, Any]
    payload_schema: dict[str, Any]
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")


class EventOccurrence(_Model):
    """One event, as returned by a poll or POSTed to a webhook."""

    event_id: str
    name: str
    timestamp: datetime
    data: dict[str, Any]
    cursor: str | None = None
    """Subscription position after this event; webhook deliveries only."""
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")


class ListEventsParams(PaginatedRequestParams):
    """Parameters for `events/list`."""


class ListEventsResult(PaginatedResult):
    """Result of `events/list`."""

    events: list[EventDescriptor]


class PollEventsParams(RequestParams):
    """Parameters for `events/poll`."""

    name: str
    arguments: dict[str, Any] | None = None
    cursor: str | None = None
    max_age_ms: int | None = Field(default=None, ge=0)
    max_events: int | None = Field(default=None, ge=1)


class PollEventsResult(Result):
    """Result of `events/poll`."""

    events: list[EventOccurrence]
    cursor: str | None = None
    truncated: bool = False
    has_more: bool = False
    next_poll_ms: int


class WebhookDelivery(_Model):
    """Where and how to deliver a webhook subscription's events."""

    mode: str = "webhook"
    url: str
    secret: str


class WebhookTarget(_Model):
    """The callback URL that identifies a webhook subscription on `events/unsubscribe`."""

    url: str


class DeliveryStatus(_Model):
    """How delivery to a webhook subscription is going, reported on refresh."""

    active: bool
    last_delivery_at: datetime | None = None
    last_error: DeliveryError | None = None
    failed_since: datetime | None = None


class SubscribeEventsParams(RequestParams):
    """Parameters for `events/subscribe`."""

    name: str
    arguments: dict[str, Any] | None = None
    delivery: WebhookDelivery
    cursor: str | None = None
    max_age_ms: int | None = Field(default=None, ge=0)
    ttl_ms: int | None = Field(default=None, ge=0)
    """Suggested lifetime; omitted means the server default, an explicit `None` asks for no expiry."""


class SubscribeEventsResult(Result):
    """Result of `events/subscribe`."""

    id: str
    refresh_before: datetime | None = None
    cursor: str | None = None
    truncated: bool = False
    delivery_status: DeliveryStatus | None = None


class UnsubscribeEventsParams(RequestParams):
    """Parameters for `events/unsubscribe`."""

    name: str
    arguments: dict[str, Any] | None = None
    delivery: WebhookTarget


class UnsubscribeEventsResult(Result):
    """Result of `events/unsubscribe`."""


class ListEventsRequest(Request[ListEventsParams | None, Literal["events/list"]]):
    method: Literal["events/list"] = "events/list"
    params: ListEventsParams | None = None


class PollEventsRequest(Request[PollEventsParams, Literal["events/poll"]]):
    method: Literal["events/poll"] = "events/poll"
    params: PollEventsParams
    name_param = "name"


class SubscribeEventsRequest(Request[SubscribeEventsParams, Literal["events/subscribe"]]):
    method: Literal["events/subscribe"] = "events/subscribe"
    params: SubscribeEventsParams
    name_param = "name"


class UnsubscribeEventsRequest(Request[UnsubscribeEventsParams, Literal["events/unsubscribe"]]):
    method: Literal["events/unsubscribe"] = "events/unsubscribe"
    params: UnsubscribeEventsParams
    name_param = "name"
