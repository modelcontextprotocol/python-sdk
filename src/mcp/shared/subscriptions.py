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

from dataclasses import dataclass
from typing import Any

from mcp_types import (
    NotificationParams,
    PromptListChangedNotification,
    ResourceListChangedNotification,
    ResourceUpdatedNotification,
    ResourceUpdatedNotificationParams,
    ServerNotification,
    ToolListChangedNotification,
)

__all__ = [
    "SUBSCRIPTION_ID_META_KEY",
    "PromptsListChanged",
    "ResourceUpdated",
    "ResourcesListChanged",
    "ServerEvent",
    "ToolsListChanged",
    "event_from_notification",
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


def event_from_notification(notification: ServerNotification) -> ServerEvent | None:
    """The event a listen-stream notification announces (the client's direction).

    Returns None for notification kinds that are not subscription events.
    """
    match notification:
        case ToolListChangedNotification():
            return ToolsListChanged()
        case PromptListChangedNotification():
            return PromptsListChanged()
        case ResourceListChangedNotification():
            return ResourcesListChanged()
        case ResourceUpdatedNotification(params=params):
            return ResourceUpdated(uri=params.uri)
        case _:
            return None
