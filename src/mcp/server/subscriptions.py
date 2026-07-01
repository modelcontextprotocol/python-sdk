"""Server-side `subscriptions/listen` support (2026-07-28, SEP-2575).

On the 2026-07-28 wire there is no standing GET stream: a client opts in to
server events by sending a `subscriptions/listen` request whose response IS
the stream. This module provides the two pieces a server needs:

- `SubscriptionBus`: the pluggable fan-out seam. The bus carries typed `ServerEvent`
  values, not wire notifications - the listen handler owns subscription-id
  stamping and per-stream filtering, so a custom bus (e.g. backed by Redis
  pub/sub for multi-replica deployments) never sees JSON-RPC. The in-process
  default is `InMemorySubscriptionBus`.
- `ListenHandler`: the request handler that serves `subscriptions/listen`.
  `MCPServer` registers one automatically; lowlevel `Server` users pass an
  instance as `on_subscriptions_listen=`.

The event vocabulary (the four `ServerEvent` dataclasses and the
`_meta` subscription-id key) is defined in `mcp.shared.subscriptions`,
shared with the client driver, and re-exported here.

Per the spec, the handler acknowledges first (the ack is the first frame on
the stream), tags every frame with the listen request's JSON-RPC id under
`_meta["io.modelcontextprotocol/subscriptionId"]`, and never delivers an
event kind the client did not request. Delivery is fire-and-forget with no
replay: a dropped stream is not resumable - clients re-listen and refetch.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

import anyio
import anyio.lowlevel
import anyio.streams.memory
from mcp_types import (
    INTERNAL_ERROR,
    INVALID_REQUEST,
    SubscriptionFilter,
    SubscriptionsAcknowledgedNotification,
    SubscriptionsAcknowledgedNotificationParams,
    SubscriptionsListenRequestParams,
    SubscriptionsListenResult,
)

from mcp.server.context import ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp.shared.subscriptions import (
    SUBSCRIPTION_ID_META_KEY,
    PromptsListChanged,
    ResourcesListChanged,
    ResourceUpdated,
    ServerEvent,
    ToolsListChanged,
    event_matches,
    event_to_notification,
)

__all__ = [
    "SUBSCRIPTION_ID_META_KEY",
    "InMemorySubscriptionBus",
    "ListenHandler",
    "PromptsListChanged",
    "ResourceUpdated",
    "ResourcesListChanged",
    "ServerEvent",
    "SubscriptionBus",
    "ToolsListChanged",
]

logger = logging.getLogger(__name__)


class SubscriptionBus(Protocol):
    """Fan-out seam between event publishers and open listen streams.

    Implement this over an external pub/sub backend (Redis, NATS, ...) to fan
    events out across replicas: `publish` forwards the event to the backend,
    and each replica's bus invokes its local listeners for events arriving
    from the backend. The same instance can be shared across servers.

    `publish` is async so backend implementations can do network I/O.
    `subscribe` is synchronous local registration. Listeners are synchronous,
    must not raise, and are invoked on the server's event loop.
    """

    async def publish(self, event: ServerEvent) -> None:
        """Deliver `event` to every subscribed listener."""
        ...

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        """Register `listener` and return an idempotent unsubscribe callable."""
        ...


class InMemorySubscriptionBus:
    """In-process `SubscriptionBus`: synchronous fan-out to listeners in subscription order."""

    def __init__(self) -> None:
        # Keyed by a per-subscription token so the same callable can be
        # registered more than once (bound methods compare equal).
        self._listeners: dict[object, Callable[[ServerEvent], None]] = {}

    async def publish(self, event: ServerEvent) -> None:
        """Deliver `event` to every subscribed listener.

        A raising listener is logged and skipped: one bad listener must not
        starve the others or fail the publishing handler. Ends with a
        checkpoint so a burst of publishes from one task lets listen streams
        drain between events instead of overflowing their buffers unread.
        """
        for listener in list(self._listeners.values()):
            try:
                listener(event)
            except Exception:  # fan-out boundary: isolate listeners from each other
                logger.exception("subscription listener raised; continuing")
        await anyio.lowlevel.checkpoint()

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        """Register `listener` and return an idempotent unsubscribe callable."""
        token = object()
        self._listeners[token] = listener

        def unsubscribe() -> None:
            self._listeners.pop(token, None)

        return unsubscribe


def _safe_unsubscribe(unsubscribe: Callable[[], None]) -> None:
    """Run a bus's unsubscribe callable, isolating the stream from it raising.

    The callable comes from a custom `SubscriptionBus`; a raising one is
    logged and skipped so it cannot stop the stream's own cleanup from
    releasing its subscription slot.
    """
    try:
        unsubscribe()
    except Exception:  # fan-out boundary: a raising bus must not skip stream cleanup
        logger.exception("bus unsubscribe raised; continuing stream cleanup")


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


class ListenHandler:
    """Serves `subscriptions/listen`: one call is one subscription stream.

    Register on a lowlevel `Server` via `on_subscriptions_listen=` (or
    `add_request_handler`); `MCPServer` does so automatically. Each call
    acknowledges the honored filter first, then forwards matching bus events
    onto the request's response stream until the client disconnects (which
    cancels the handler; the stream just ends, per the spec's abrupt-close
    contract) or `close` ends all streams gracefully.

    Requires a transport that can stream a request's response (streamable
    HTTP's SSE mode).

    `max_subscriptions` bounds concurrent streams (further listen requests are
    rejected with `INTERNAL_ERROR`, before the ack). `max_buffered_events`
    bounds each stream's event backlog: a stream whose client has stopped
    reading is ended at the cap (the client re-listens and refetches - there
    is no replay, so ending the stream loses nothing the backlog wasn't
    already losing).
    """

    def __init__(self, bus: SubscriptionBus, *, max_subscriptions: int = 1024, max_buffered_events: int = 1024) -> None:
        self._bus = bus
        self._max_subscriptions = max_subscriptions
        self._max_buffered_events = max_buffered_events
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
        if len(self._streams) >= self._max_subscriptions:
            raise MCPError(INTERNAL_ERROR, "Subscription limit reached")
        honored = _honored_subset(params.notifications)
        honored_uris = frozenset(honored.resource_subscriptions or ())
        meta: dict[str, Any] = {SUBSCRIPTION_ID_META_KEY: subscription_id}

        # Buffered so publishers don't block on a slow consumer (the transport
        # write happens in this handler task, not the publisher's). A stream
        # whose backlog hits the cap is ended - see the class docstring.
        send, recv = anyio.create_memory_object_stream[ServerEvent](self._max_buffered_events)

        def deliver(event: ServerEvent) -> None:
            if event_matches(honored, honored_uris, event):
                try:
                    send.send_nowait(event)
                except anyio.ClosedResourceError:
                    # `close` closed this stream; the loop below is unwinding.
                    pass
                except anyio.WouldBlock:
                    logger.warning("listen stream %r backlog full; ending the stream", subscription_id)
                    # Release the subscription slot now: the handler's own
                    # cleanup can be wedged in a transport write that closing
                    # this buffer cannot wake (a client that stopped reading).
                    self._streams.discard(send)
                    send.close()

        # Subscribe before sending the ack so an event published while the
        # ack write is suspended is buffered rather than lost. The ack is
        # still the first frame: this task alone writes the stream, and it
        # only starts draining the buffer after the ack send returns.
        unsubscribe = self._bus.subscribe(deliver)
        self._streams.add(send)
        try:
            await ctx.session.send_notification(
                SubscriptionsAcknowledgedNotification(
                    params=SubscriptionsAcknowledgedNotificationParams(notifications=honored, _meta=meta)
                ),
                related_request_id=subscription_id,
            )
            async for event in recv:
                await ctx.session.send_notification(
                    event_to_notification(event, meta), related_request_id=subscription_id
                )
        finally:
            _safe_unsubscribe(unsubscribe)
            self._streams.discard(send)
            send.close()
            recv.close()
        return SubscriptionsListenResult(_meta=meta)

    def close(self) -> None:
        """Initiate graceful closure of every open listen stream.

        Each stream then drains its buffered events and sends its
        `SubscriptionsListenResult` (stamped with the subscription id) as the
        final frame from its own handler task - the spec's graceful closure
        flow, telling clients the stream ended deliberately rather than
        dropping. This method only initiates that; it does not wait for the
        streams to finish flushing.
        """
        for stream in list(self._streams):
            stream.close()
