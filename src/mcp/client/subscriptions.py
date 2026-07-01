"""Client-side `subscriptions/listen` driver (2026-07-28, SEP-2575).

`listen()` opens the stream as an async context manager: entering waits for
the server's acknowledgment, iteration yields typed change events, a graceful
server close ends the loop, and an abrupt drop raises `SubscriptionLost`.
There is no replay and no automatic re-listen: a client that re-opens a
subscription refetches what it depends on.
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
"""Backlog backstop: the spec allows sub-resource URIs, so distinct pending
`ResourceUpdated` events are unbounded; overflowing this cap settles the
subscription lost rather than growing client memory."""

_SubscriptionEnd = Literal["graceful", "lost", "local"]


class ListenNotSupportedError(RuntimeError):
    """`subscriptions/listen` requires a 2026-07-28 connection."""

    def __init__(self, negotiated_version: str | None) -> None:
        self.negotiated_version = negotiated_version
        super().__init__(
            f"subscriptions/listen is not available at protocol version {negotiated_version!r}; it requires "
            "2026-07-28. On earlier versions use subscribe_resource() and the change notifications delivered "
            "through message_handler."
        )


class SubscriptionLost(RuntimeError):
    """The stream ended without the server's graceful close; re-listen and refetch."""


class ListenRoute:
    """Package-internal demux state for one listen stream, fed synchronously in receive order by the session."""

    def __init__(self) -> None:
        self.honored: types.SubscriptionFilter | None = None
        self.acked = anyio.Event()
        self.error: MCPError | None = None
        self.end: _SubscriptionEnd | None = None
        self._honored_uris: frozenset[str] = frozenset()
        self._pending: dict[ServerEvent, None] = {}
        self._wake = anyio.Event()

    def set_acked(self, honored: types.SubscriptionFilter) -> None:
        """Record the acknowledged filter; the first ack wins."""
        if not self.acked.is_set():
            self.honored = honored
            self._honored_uris = frozenset(honored.resource_subscriptions or ())
            self.acked.set()

    def deliver(self, event: ServerEvent) -> None:
        """Queue an event within the honored filter, deduplicated against the backlog.

        Any `ResourceUpdated` is admitted once URI subscriptions were honored at
        all: the spec allows the stamped URI to be a sub-resource of a subscribed one.
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
        """Record the stream's end; the first reason wins and wakes both waiters."""
        if self.end is None:
            self.end = end
            self.error = error
            self.acked.set()
            self._wake.set()

    async def next_event(self) -> ServerEvent | _SubscriptionEnd:
        """Peek the next pending event, or the stream's end once the backlog drains.

        A "local" end short-circuits the backlog; the other endings drain it first,
        so a graceful close never swallows events that preceded it.
        """
        while True:
            # Snapshot the wake event before checking state so a deliver landing after the checks cannot be missed.
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
        """Remove a peeked event from the backlog."""
        self._pending.pop(event, None)


OnEvent = Callable[[ServerEvent], Awaitable[None]]
"""Per-event barrier awaited before a `Subscription` returns each event to its consumer."""


class Subscription:
    """One open `subscriptions/listen` stream: an async iterator of typed events.

    Produced by `listen()` / `Client.listen()`, not constructed directly.
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
        """The listen request's JSON-RPC id, stamped into every frame's `_meta`."""
        self.honored = honored
        """The subset of the requested filter the server agreed to deliver."""

    def __aiter__(self) -> Subscription:
        return self

    async def __anext__(self) -> ServerEvent:
        """Yield the next change event; the loop ends when the stream does.

        Raises:
            SubscriptionLost: the stream dropped without the server's graceful close.
        """
        outcome = await self._route.next_event()
        if isinstance(outcome, str):
            if outcome == "lost":
                raise SubscriptionLost(
                    f"subscription {self.subscription_id!r} ended without the server's graceful close;"
                    " re-listen and refetch"
                ) from self._route.error
            raise StopAsyncIteration
        if self._on_event is not None:
            # The event stays pending while the barrier runs: a cancellation or a
            # raising barrier leaves it for the next anext instead of dropping it.
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

    Entering sends the request and returns once the server's acknowledgment
    arrives; exiting ends the subscription. `on_event` is awaited before each
    event is returned - the seam `Client.listen` uses to finish cache eviction
    before the consumer can refetch.

    Raises:
        ListenNotSupportedError: negotiated version predates 2026-07-28.
        MCPError: the server rejected the request, or the connection failed pre-ack.
        SubscriptionLost: the stream ended before it was acknowledged.
        TimeoutError: the session's read timeout elapsed before the acknowledgment.
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
        # Deliberately no result timeout: the response arrives when the stream ends.
        with driver_scope:
            try:
                await session._dispatcher.send_raw_request(  # pyright: ignore[reportPrivateUsage]
                    data["method"], data.get("params"), opts
                )
            except MCPError as error:
                route.settle("lost", error=error)
                return
            except ValueError as error:
                # A raw request id collided with our minted listen id: fail this subscription
                # and release the route in this same slice, so it cannot consume the raw caller's ack.
                session._unregister_listen_route(request_id)  # pyright: ignore[reportPrivateUsage]
                route.settle("lost", error=MCPError(types.INTERNAL_ERROR, str(error)))
                return
            # A result, whatever its body, is the spec's graceful close; with no prior ack
            # it opens the subscription already closed.
            route.set_acked(types.SubscriptionFilter())
            route.settle("graceful")

    # Register the demux route before the request is written so the ack cannot race it.
    route = session._register_listen_route(request_id)  # pyright: ignore[reportPrivateUsage]
    try:
        task_group.start_soon(drive)
        with anyio.fail_after(session._session_read_timeout_seconds):  # pyright: ignore[reportPrivateUsage]
            await route.acked.wait()
        if route.honored is None:
            # Only reachable on failure paths: a graceful no-ack result acked an empty filter in drive().
            if route.error is not None:
                raise route.error
            raise SubscriptionLost(f"subscription {request_id!r} ended before it was acknowledged")
        yield Subscription(route, request_id, route.honored, on_event)
    finally:
        route.settle("local")
        driver_scope.cancel()
        session._unregister_listen_route(request_id)  # pyright: ignore[reportPrivateUsage]
