"""The typed event vocabulary `subscriptions/listen` shares between server and client (2026-07-28, SEP-2575).

A server publishes these events (`mcp.server.subscriptions`); a client
iterating a `Subscription` (`mcp.client.subscriptions`) receives the same
values back. The two conversion helpers map between events and their wire
notifications, one direction per side.

Every event kind is a level trigger: it says "this changed, refetch if you
care", and carries no payload beyond identity - so two equal pending events
mean exactly what one means, which is what lets both sides bound their
buffers by deduplication.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from mcp_types import (
    NotificationParams,
    PromptListChangedNotification,
    ResourceListChangedNotification,
    ResourceUpdatedNotification,
    ResourceUpdatedNotificationParams,
    ServerNotification,
    SubscriptionFilter,
    ToolListChangedNotification,
)

__all__ = [
    "SUBSCRIPTION_ID_META_KEY",
    "PromptsListChanged",
    "ResourceUpdated",
    "ResourcesListChanged",
    "ServerEvent",
    "ToolsListChanged",
    "event_from_wire",
    "event_matches",
    "event_to_notification",
]

SUBSCRIPTION_ID_META_KEY = "io.modelcontextprotocol/subscriptionId"
"""The `_meta` key carrying the subscription id on every listen-stream frame.

The value is the `subscriptions/listen` request's JSON-RPC id, verbatim.
"""


@dataclass(frozen=True)
class ToolsListChanged:
    """The server's tool list changed."""


@dataclass(frozen=True)
class PromptsListChanged:
    """The server's prompt list changed."""


@dataclass(frozen=True)
class ResourcesListChanged:
    """The server's resource list changed."""


@dataclass(frozen=True)
class ResourceUpdated:
    """The resource at `uri` changed and may need to be read again."""

    uri: str


ServerEvent = ToolsListChanged | PromptsListChanged | ResourcesListChanged | ResourceUpdated
"""An event a server publishes for delivery to listen subscribers."""


def event_to_notification(event: ServerEvent, meta: dict[str, Any]) -> ServerNotification:
    """Build the stamped wire notification for `event` (the server's direction)."""
    if isinstance(event, ToolsListChanged):
        return ToolListChangedNotification(params=NotificationParams(_meta=meta))
    if isinstance(event, PromptsListChanged):
        return PromptListChangedNotification(params=NotificationParams(_meta=meta))
    if isinstance(event, ResourcesListChanged):
        return ResourceListChangedNotification(params=NotificationParams(_meta=meta))
    return ResourceUpdatedNotification(params=ResourceUpdatedNotificationParams(uri=event.uri, _meta=meta))


_LIST_CHANGED_EVENTS: dict[str, ServerEvent] = {
    "notifications/tools/list_changed": ToolsListChanged(),
    "notifications/prompts/list_changed": PromptsListChanged(),
    "notifications/resources/list_changed": ResourcesListChanged(),
}


def event_from_wire(method: str, params: Mapping[str, Any] | None) -> ServerEvent | None:
    """The event a raw listen-stream frame announces (the client's direction).

    Reads the wire dict directly: the client demultiplexes on the dispatcher's
    receive path, before the typed notification parse. Returns None for
    non-event methods, and for a `resources/updated` frame with no string
    `uri` (surface validation rejects those shapes downstream).
    """
    if (event := _LIST_CHANGED_EVENTS.get(method)) is not None:
        return event
    if method == "notifications/resources/updated":
        uri = (params or {}).get("uri")
        if isinstance(uri, str):
            return ResourceUpdated(uri=uri)
    return None


def event_matches(honored: SubscriptionFilter, uris: frozenset[str], event: ServerEvent) -> bool:
    """Whether `event` is within a stream's honored filter.

    The one admission predicate both sides share: the server delivers only
    what it acknowledged, and the client admits only what was acknowledged -
    which is what bounds the client's backlog by the filter's width against
    any peer, honest or not. `uris` is the honored `resource_subscriptions`
    as a set: matching runs on every event, and the filter may name many URIs.
    """
    if isinstance(event, ToolsListChanged):
        return honored.tools_list_changed is True
    if isinstance(event, PromptsListChanged):
        return honored.prompts_list_changed is True
    if isinstance(event, ResourcesListChanged):
        return honored.resources_list_changed is True
    return event.uri in uris
