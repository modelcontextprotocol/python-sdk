"""Client-side `subscriptions/listen` driver (2026-07-28, SEP-2575).

On the 2026 wire a client opts in to server change notifications by sending
one `subscriptions/listen` request whose response IS the stream. This module
turns that into an async context manager:

    async with client.listen(tools_list_changed=True) as sub:
        async for event in sub:
            ...  # ToolsListChanged() - go refetch

Entering waits for the server's acknowledgment, so `sub.honored` (the subset
of the requested filter the server agreed to deliver) is always populated.
Iteration yields the same typed events the server publishes. The stream's two
endings are control flow: a graceful server close simply ends the loop, an
abrupt drop raises `SubscriptionLost`. Exiting the context ends the
subscription with the transport's own cancellation spelling (aborting the
request's stream over streamable HTTP, `notifications/cancelled` on stream
transports). There is no replay and no automatic re-listen: a client that
re-opens a subscription refetches what it depends on.

`listen(session, ...)` is the composable helper for callers holding a bare
`ClientSession`; `Client.listen(...)` is the high-level spelling.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from itertools import count
from typing import TYPE_CHECKING, Literal

import anyio
import mcp_types as types
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

from mcp.shared.dispatcher import CallOptions
from mcp.shared.exceptions import MCPError
from mcp.shared.subscriptions import (
    PromptsListChanged,
    ResourcesListChanged,
    ResourceUpdated,
    ServerEvent,
    ToolsListChanged,
    event_matches,
)

if TYPE_CHECKING:
    from mcp.client.session import ClientSession

__all__ = [
    "ListenNotSupportedError",
    "OnEvent",
    "PromptsListChanged",
    "ResourceUpdated",
    "ResourcesListChanged",
    "ServerEvent",
    "Subscription",
    "SubscriptionLost",
    "ToolsListChanged",
    "listen",
]

_listen_ids = count(1)
"""Process-wide `listen-N` sequence: string ids can never collide with a dispatcher's minted ints."""

_MAX_PENDING_EVENTS = 1024
"""Backstop on one route's unconsumed backlog, mirroring the server's `max_buffered_events`.

Kind events are bounded by dedupe alone, but `ResourceUpdated` admission is
per-URI and the spec lets a server stamp sub-resources of a subscribed URI -
so distinct pending URIs are unbounded in principle. A peer that floods past
this cap costs the subscription (settled lost: re-listen and refetch), never
unbounded client memory.
"""

_SubscriptionEnd = Literal["graceful", "lost", "local"]


class ListenNotSupportedError(RuntimeError):
    """`subscriptions/listen` requires a 2026-07-28 connection.

    On earlier protocol versions, subscribe with `subscribe_resource()` and
    receive change notifications through the session's `message_handler`.
    """

    def __init__(self, negotiated_version: str | None) -> None:
        self.negotiated_version = negotiated_version
        super().__init__(
            f"subscriptions/listen is not available at protocol version {negotiated_version!r}; it requires "
            "2026-07-28. On earlier versions use subscribe_resource() and the change notifications delivered "
            "through message_handler."
        )


class SubscriptionLost(RuntimeError):
    """The subscription's stream ended without the server's graceful close.

    The transport dropped, or the server tore the stream down abruptly. There
    is no replay: re-open with `listen()` and refetch what you depend on.
    """


class ListenRoute:
    """Demux state for one listen stream, fed in wire order by the session.

    Package-internal (deliberately not in `__all__`): `ClientSession`
    constructs it and feeds it from its notification intercept on the
    dispatcher's receive path, so acks, events, and stream-teardown signals
    land here in receive order - ordered against the listen request's own
    result, which resolves on that same path. `Subscription` is the one
    consumer.

    Everything here is synchronous on the event loop - the receive path must
    never block on a slow consumer. Pending events deduplicate: every event
    kind is a level trigger, so the backlog is bounded by the distinct
    admissible events, with `_MAX_PENDING_EVENTS` as the backstop for the
    URI class that admission deliberately leaves open.
    """

    def __init__(self) -> None:
        self.honored: types.SubscriptionFilter | None = None
        self.acked = anyio.Event()
        self.error: MCPError | None = None
        self.end: _SubscriptionEnd | None = None
        self._honored_uris: frozenset[str] = frozenset()
        self._pending: dict[ServerEvent, None] = {}
        self._wake = anyio.Event()

    def set_acked(self, honored: types.SubscriptionFilter) -> None:
        """Record the acknowledged filter; the first ack wins, later ones are no-ops."""
        if not self.acked.is_set():
            self.honored = honored
            self._honored_uris = frozenset(honored.resource_subscriptions or ())
            self.acked.set()

    def deliver(self, event: ServerEvent) -> None:
        """Queue `event` for the consumer; duplicates of pending events are dropped.

        Only events within the honored filter are admitted, so a peer that
        violates its own acknowledgment cannot reach the consumer. Kind events
        match the honored flags exactly; a `ResourceUpdated` is admitted
        whenever URI subscriptions were honored at all, because the spec lets
        the stamped URI be a sub-resource of a subscribed one (schema:
        ResourceUpdatedNotificationParams.uri). Before the ack there is no
        honored filter and nothing is admissible (the spec makes the ack the
        stream's first frame); after the stream has ended a frame can only be
        post-close noise. `_MAX_PENDING_EVENTS` backstops the one backlog
        admission cannot bound.
        """
        if self.end is not None or self.honored is None:
            return
        if isinstance(event, ResourceUpdated):
            admitted = bool(self._honored_uris)
        else:
            admitted = event_matches(self.honored, self._honored_uris, event)
        if not admitted or event in self._pending:
            return
        if len(self._pending) >= _MAX_PENDING_EVENTS:
            self.settle(
                "lost",
                error=MCPError(
                    types.INTERNAL_ERROR,
                    f"subscription backlog exceeded {_MAX_PENDING_EVENTS} unconsumed events; re-listen and refetch",
                ),
            )
            return
        self._pending[event] = None
        self._wake.set()

    def settle(self, end: _SubscriptionEnd, error: MCPError | None = None) -> None:
        """Record the stream's end; the first reason wins.

        Also wakes the ack waiter so a pre-ack failure surfaces immediately.
        """
        if self.end is None:
            self.end = end
            self.error = error
            self.acked.set()
            self._wake.set()

    async def next_event(self) -> ServerEvent | _SubscriptionEnd:
        """Return (but do not remove) the next pending event, or the stream's end once drained.

        The consumer removes the event with `consume()` only after its own
        pre-return work (the `Subscription`'s `on_event` barrier) completed -
        a cancellation landing mid-barrier leaves the event pending, so a
        delivered event is never lost to the consumer's own timeout.

        A "local" end short-circuits the backlog: the consumer left the
        context, so buffered events must not read as live deliveries. The
        other endings drain first - a graceful close never swallows events
        that preceded it.
        """
        while True:
            # Snapshot the wake event BEFORE checking state: a deliver landing
            # after the checks sets this same object, so the wait cannot miss it.
            wake = self._wake
            if self.end == "local":
                return self.end
            if self._pending:
                return next(iter(self._pending))
            if self.end is not None:
                return self.end
            await wake.wait()
            self._wake = anyio.Event()

    def consume(self, event: ServerEvent) -> None:
        """Remove a peeked event from the backlog; the consumer commits after its barrier ran."""
        self._pending.pop(event, None)


OnEvent = Callable[[ServerEvent], Awaitable[None]]
"""Per-event barrier awaited before a `Subscription` returns each event to its consumer."""


class Subscription:
    """One open `subscriptions/listen` stream: an async iterator of typed events.

    Produced by `listen()` / `Client.listen()`, not constructed directly.
    Buffered events are served before the stream's end is reported, so a
    graceful close never swallows deliveries that preceded it.
    """

    def __init__(
        self,
        route: ListenRoute,
        subscription_id: types.RequestId,
        honored: types.SubscriptionFilter,
        on_event: OnEvent | None = None,
    ):
        self._route = route
        self._on_event = on_event
        self.subscription_id = subscription_id
        """The listen request's JSON-RPC id - the value stamped into every frame's `_meta`."""
        self.honored = honored
        """The subset of the requested filter the server agreed to deliver (the acknowledgment)."""

    def __aiter__(self) -> Subscription:
        return self

    async def __anext__(self) -> ServerEvent:
        """Yield the next change event; the loop ends when the stream does.

        Raises:
            SubscriptionLost: The stream dropped without the server's graceful close.
        """
        outcome = await self._route.next_event()
        if isinstance(outcome, str):
            if outcome == "lost":
                raise SubscriptionLost(
                    f"subscription {self.subscription_id!r} ended without the server's graceful close;"
                    " re-listen and refetch"
                ) from self._route.error
            # "graceful" (the server's deliberate close) and "local" (the
            # consumer already left the context) both end iteration cleanly.
            raise StopAsyncIteration
        if self._on_event is not None:
            # The barrier completes before the consumer can act on the event -
            # `Client.listen` finishes response-cache eviction here, so an
            # event-triggered refetch can never be served the pre-event entry.
            # The event is still pending while the barrier runs: a cancellation
            # (or a raising barrier) leaves it for the next `anext` instead of
            # silently dropping a level trigger that would never re-fire.
            await self._on_event(outcome)
        self._route.consume(outcome)
        return outcome


@asynccontextmanager
async def listen(
    session: ClientSession,
    *,
    tools_list_changed: bool = False,
    prompts_list_changed: bool = False,
    resources_list_changed: bool = False,
    resource_subscriptions: Sequence[str] = (),
    on_event: OnEvent | None = None,
) -> AsyncIterator[Subscription]:
    """Open one `subscriptions/listen` stream on `session` (2026-07-28 only).

    The filter keyword arguments mirror the wire `SubscriptionFilter` field
    for field; `resource_subscriptions` names exact resource URIs to watch for
    `ResourceUpdated` events. Entering sends the request and returns once the
    server's acknowledgment arrives (bounded by the session's read timeout,
    when one is set). Exiting ends the subscription. Multiple subscriptions
    may be open concurrently; each demultiplexes by its own subscription id.

    `on_event` is awaited before each event is returned from the iterator -
    the seam for work that must complete before the consumer can react.
    `Client.listen` finishes response-cache eviction here so an
    event-triggered refetch cannot be served the pre-event entry; callers
    opening a stream on a cached `Client`'s session directly should wire the
    same barrier themselves (or use `Client.listen`). A raising barrier
    surfaces from the iteration, with the event left pending for the next
    `anext`.

    Raises:
        ListenNotSupportedError: The negotiated protocol version predates 2026-07-28.
        MCPError: The server rejected the request, or the connection failed
            before the acknowledgment arrived.
        SubscriptionLost: The stream ended before it was acknowledged.
        TimeoutError: The session's read timeout elapsed before the acknowledgment.
    """
    if session.protocol_version not in MODERN_PROTOCOL_VERSIONS:
        raise ListenNotSupportedError(session.protocol_version)
    if isinstance(resource_subscriptions, str):
        raise TypeError("resource_subscriptions takes a sequence of URIs, not a bare string")
    request = types.SubscriptionsListenRequest(
        params=types.SubscriptionsListenRequestParams(
            notifications=types.SubscriptionFilter(
                tools_list_changed=tools_list_changed or None,
                prompts_list_changed=prompts_list_changed or None,
                resources_list_changed=resources_list_changed or None,
                resource_subscriptions=list(resource_subscriptions) or None,
            )
        )
    )
    task_group = session._task_group  # pyright: ignore[reportPrivateUsage]
    if task_group is None:
        raise RuntimeError("listen() requires an entered session")
    request_id: types.RequestId = f"listen-{next(_listen_ids)}"
    data = request.model_dump(by_alias=True, mode="json", exclude_none=True)
    opts: CallOptions = {"request_id": request_id}
    session._stamp(data, opts)  # pyright: ignore[reportPrivateUsage]
    driver_scope = anyio.CancelScope()

    async def drive() -> None:
        # The listen request deliberately carries no result timeout: its
        # response arrives when the stream ends, however long that takes.
        with driver_scope:
            try:
                await session._dispatcher.send_raw_request(  # pyright: ignore[reportPrivateUsage]
                    data["method"], data.get("params"), opts
                )
            except MCPError as error:
                route.settle("lost", error=error)
                return
            except ValueError as error:
                # A caller-supplied raw request id collided with our minted
                # listen id: fail this subscription, not the whole session.
                # The id belongs to the raw caller, so release the demux
                # registration in this same slice - a registered route would
                # consume the raw caller's own ack while this open unwinds.
                session._unregister_listen_route(request_id)  # pyright: ignore[reportPrivateUsage]
                route.settle("lost", error=MCPError(types.INTERNAL_ERROR, str(error)))
                return
            # The empty result is the spec's graceful close. Tolerant by design:
            # receiving it IS the signal, whatever its body. A result with no
            # prior ack opens the subscription already closed.
            route.set_acked(types.SubscriptionFilter())
            route.settle("graceful")

    # Register the demux route before the request is written so the ack can
    # never race it; from here the finally owns cleanup, so a failing spawn
    # cannot leak the registration.
    route = session._register_listen_route(request_id)  # pyright: ignore[reportPrivateUsage]
    try:
        task_group.start_soon(drive)
        with anyio.fail_after(session._session_read_timeout_seconds):  # pyright: ignore[reportPrivateUsage]
            await route.acked.wait()
        if route.honored is None:
            # No ack means no subscription: raise, don't degrade. (A graceful
            # result with no ack acked an empty filter in drive(), so honored
            # is None here only on the failure paths.)
            if route.error is not None:
                raise route.error
            raise SubscriptionLost(f"subscription {request_id!r} ended before it was acknowledged")
        yield Subscription(route, request_id, route.honored, on_event)
    finally:
        route.settle("local")
        driver_scope.cancel()
        session._unregister_listen_route(request_id)  # pyright: ignore[reportPrivateUsage]
