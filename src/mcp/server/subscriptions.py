"""Server-side `subscriptions/listen` support (2026-07-28, SEP-2575).

On the 2026-07-28 wire there is no standing GET stream: a client opts in to
server events by sending a `subscriptions/listen` request whose response IS
the stream. This module provides the two pieces a server needs:

- `EventBus`: the pluggable fan-out seam. The bus carries typed `ServerEvent`
  values, not wire notifications - the listen handler owns subscription-id
  stamping and per-stream filtering, so a custom bus (e.g. backed by Redis
  pub/sub for multi-replica deployments) never sees JSON-RPC. The in-process
  default is `InMemoryEventBus`.
- `ListenHandler`: the request handler that serves `subscriptions/listen`.
  `MCPServer` registers one automatically; lowlevel `Server` users pass an
  instance as `on_subscriptions_listen=`.

Per the spec, the handler acknowledges first (the ack is the first frame on
the stream), tags every frame with the listen request's JSON-RPC id under
`_meta["io.modelcontextprotocol/subscriptionId"]`, and never delivers an
event kind the client did not request. Delivery is fire-and-forget with no
replay: a dropped stream is not resumable - clients re-listen and refetch.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import anyio
import anyio.streams.memory
from mcp_types import (
    INVALID_REQUEST,
    NotificationParams,
    PromptListChangedNotification,
    ResourceListChangedNotification,
    ResourceUpdatedNotification,
    ResourceUpdatedNotificationParams,
    ServerNotification,
    SubscriptionFilter,
    SubscriptionsAcknowledgedNotification,
    SubscriptionsAcknowledgedNotificationParams,
    SubscriptionsListenRequestParams,
    SubscriptionsListenResult,
    ToolListChangedNotification,
)

from mcp.server.context import ServerRequestContext
from mcp.shared.exceptions import MCPError

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


class EventBus(Protocol):
    """Fan-out seam between event publishers and open listen streams.

    Implement this over an external pub/sub backend (Redis, NATS, ...) to fan
    events out across replicas: `publish` forwards the event to the backend,
    and each replica's bus invokes its local listeners for events arriving
    from the backend. The same instance can be shared across servers.

    Both methods are synchronous and must be called from the server's event
    loop thread. Listeners must not raise.
    """

    def publish(self, event: ServerEvent) -> None:
        """Deliver `event` to every subscribed listener."""
        ...

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        """Register `listener` and return an idempotent unsubscribe callable."""
        ...


class InMemoryEventBus:
    """In-process `EventBus`: synchronous fan-out to a set of listeners."""

    def __init__(self) -> None:
        self._listeners: set[Callable[[ServerEvent], None]] = set()

    def publish(self, event: ServerEvent) -> None:
        """Deliver `event` to every subscribed listener."""
        for listener in list(self._listeners):
            listener(event)

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        """Register `listener` and return an idempotent unsubscribe callable."""
        self._listeners.add(listener)

        def unsubscribe() -> None:
            self._listeners.discard(listener)

        return unsubscribe


def _honored_subset(requested: SubscriptionFilter) -> SubscriptionFilter:
    """The subset of `requested` the server will deliver, for the ack.

    Every requested kind is honored - whether an event kind ever fires
    depends on what the server publishes, exactly as a subscription to a
    nonexistent resource URI is honored and never fires. Non-true flags and
    an empty URI list are dropped rather than echoed as falsy values.
    """
    return SubscriptionFilter(
        tools_list_changed=True if requested.tools_list_changed else None,
        prompts_list_changed=True if requested.prompts_list_changed else None,
        resources_list_changed=True if requested.resources_list_changed else None,
        resource_subscriptions=list(requested.resource_subscriptions) if requested.resource_subscriptions else None,
    )


def _event_matches(honored: SubscriptionFilter, event: ServerEvent) -> bool:
    """Whether `event` is within the stream's honored filter."""
    if isinstance(event, ToolsListChanged):
        return honored.tools_list_changed is True
    if isinstance(event, PromptsListChanged):
        return honored.prompts_list_changed is True
    if isinstance(event, ResourcesListChanged):
        return honored.resources_list_changed is True
    return honored.resource_subscriptions is not None and event.uri in honored.resource_subscriptions


def _event_to_notification(event: ServerEvent, meta: dict[str, Any]) -> ServerNotification:
    """Build the stamped wire notification for `event`."""
    if isinstance(event, ToolsListChanged):
        return ToolListChangedNotification(params=NotificationParams(_meta=meta))
    if isinstance(event, PromptsListChanged):
        return PromptListChangedNotification(params=NotificationParams(_meta=meta))
    if isinstance(event, ResourcesListChanged):
        return ResourceListChangedNotification(params=NotificationParams(_meta=meta))
    return ResourceUpdatedNotification(params=ResourceUpdatedNotificationParams(uri=event.uri, _meta=meta))


class ListenHandler:
    """Serves `subscriptions/listen`: one call is one subscription stream.

    Register on a lowlevel `Server` via `on_subscriptions_listen=` (or
    `add_request_handler`); `MCPServer` does so automatically. Each call
    acknowledges the honored filter first, then forwards matching bus events
    onto the request's response stream until the client disconnects (which
    cancels the handler; the stream just ends, per the spec's abrupt-close
    contract) or `close` ends all streams gracefully.

    Requires a transport that can stream a request's response (streamable
    HTTP's SSE mode, stdio).
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._streams: set[anyio.streams.memory.MemoryObjectSendStream[ServerEvent]] = set()

    async def __call__(
        self,
        ctx: ServerRequestContext[Any, Any],
        params: SubscriptionsListenRequestParams,
    ) -> SubscriptionsListenResult:
        """Serve one listen stream."""
        subscription_id = ctx.request_id
        if subscription_id is None:
            raise MCPError(INVALID_REQUEST, "subscriptions/listen requires a request id")
        honored = _honored_subset(params.notifications)
        meta: dict[str, Any] = {SUBSCRIPTION_ID_META_KEY: subscription_id}

        # Ack first, subscribe second: no event can precede the ack frame.
        await ctx.session.send_notification(
            SubscriptionsAcknowledgedNotification(
                params=SubscriptionsAcknowledgedNotificationParams(notifications=honored, _meta=meta)
            ),
            related_request_id=subscription_id,
        )

        # Unbounded buffer so publishers never block on a slow consumer (the
        # transport write happens in this handler task, not the publisher's).
        send, recv = anyio.create_memory_object_stream[ServerEvent](math.inf)

        def deliver(event: ServerEvent) -> None:
            if _event_matches(honored, event):
                try:
                    send.send_nowait(event)
                except anyio.ClosedResourceError:
                    # `aclose` closed this stream; the loop below is unwinding.
                    pass

        unsubscribe = self._bus.subscribe(deliver)
        self._streams.add(send)
        try:
            async for event in recv:
                await ctx.session.send_notification(
                    _event_to_notification(event, meta), related_request_id=subscription_id
                )
        finally:
            unsubscribe()
            self._streams.discard(send)
            send.close()
            recv.close()
        return SubscriptionsListenResult(_meta=meta)

    def close(self) -> None:
        """Gracefully end every open listen stream.

        Each stream sends its `SubscriptionsListenResult` (stamped with the
        subscription id) as the final frame and closes - the spec's graceful
        closure flow, signalling clients not to re-listen.
        """
        for stream in list(self._streams):
            stream.close()
